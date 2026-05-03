from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMimeData, QPoint
from PySide6.QtGui import QColor, QDrag, QPainter, QPixmap
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import CONFIG_DIR
from .widgets import MenuSelectorButton, NoWheelSlider
from .window_geometry import install_window_geometry

SOUNDBOARD_PATH = CONFIG_DIR / "soundboard.json"
SOUNDBOARD_PAIRING_PATH = CONFIG_DIR / "soundboard_pairing.json"
SOUNDBOARD_PAIRING_TTL_SECONDS = 300
SOUNDBOARD_CACHE_DIR = CONFIG_DIR / "soundboard-cache"
SOUNDBOARD_LAST_DIR_PATH = CONFIG_DIR / "soundboard_last_dir.txt"
SOUNDBOARD_LOUDNORM_I = -18.0
SOUNDBOARD_LOUDNORM_TP = -1.5
SOUNDBOARD_LIMITER_LIMIT = 0.95
SUPPORTED_AUDIO_FILTER = "Audio files (*.wav *.wave *.ogg *.oga *.flac *.mp3 *.m4a);;All files (*)"
SOUNDBOARD_GLOBAL_VOLUME_DEFAULT = 100
SOUNDBOARD_AUTO_LEVEL_DEFAULT = False
SOUNDBOARD_TARGET_PEAK_DB = -12.0
SOUNDBOARD_TRIM_DB_DEFAULT = 0.0
SOUNDBOARD_TRIM_DB_MIN = -24
SOUNDBOARD_TRIM_DB_MAX = 24
SOUNDBOARD_PAD_SCALE_DEFAULT = 100
SOUNDBOARD_PAD_SCALE_MIN = 50
SOUNDBOARD_PAD_SCALE_MAX = 200
PLAYBACK_TARGETS = ["media", "game", "chat", "more", "all"]
SOUNDBOARD_BUS = "soundboard"
SOUNDBOARD_MONITOR_MEDIA_NAME = "K-Sound-Hub-Soundboard-Monitor"


def _slot_id(index: int) -> str:
    return f"sb{index + 1}"


def _default_slot_number(number: int) -> dict[str, Any]:
    number = max(1, int(number))
    return {
        "id": _slot_id(number - 1),
        "label": f"SOUND {number}",
        "path": "",
        "volume": 80,
        "shortcut": "",
        "output_channel": "media",
        "send_to_micro": False,
        "trim_db": SOUNDBOARD_TRIM_DB_DEFAULT,
    }


def _default_slots(count: int = 12) -> list[dict[str, Any]]:
    return [_default_slot_number(index + 1) for index in range(count)]


def _next_slot_number(slots: list[dict[str, Any]]) -> int:
    used_ids = {
        str(slot.get("id", "") or "").strip()
        for slot in slots
        if isinstance(slot, dict)
    }

    numbers: list[int] = []
    for slot_id in used_ids:
        match = re.fullmatch(r"sb(\d+)", slot_id)
        if match:
            numbers.append(int(match.group(1)))

    number = max(numbers or [0]) + 1
    while _slot_id(number - 1) in used_ids:
        number += 1

    return number


def _clean_slot(raw: dict[str, Any], fallback_index: int) -> dict[str, Any]:
    slot_id = str(raw.get("id") or _slot_id(fallback_index)).strip() or _slot_id(fallback_index)
    label = str(raw.get("label") or f"SOUND {fallback_index + 1}").strip() or f"SOUND {fallback_index + 1}"
    path = str(raw.get("path") or "").strip()
    shortcut = str(raw.get("shortcut") or "").strip()
    output_channel = str(raw.get("output_channel") or "media").strip().lower()
    if output_channel not in PLAYBACK_TARGETS:
        output_channel = "media"

    try:
        volume = int(raw.get("volume", 80))
    except Exception:
        volume = 80

    try:
        auto_gain = float(raw.get("auto_gain", 1.0))
    except Exception:
        auto_gain = 1.0
    auto_gain = max(0.05, min(1.0, auto_gain))

    analyzed_path = str(raw.get("analyzed_path") or "").strip()

    try:
        trim_db = float(raw.get("trim_db", SOUNDBOARD_TRIM_DB_DEFAULT))
    except Exception:
        trim_db = SOUNDBOARD_TRIM_DB_DEFAULT
    trim_db = max(SOUNDBOARD_TRIM_DB_MIN, min(SOUNDBOARD_TRIM_DB_MAX, trim_db))

    return {
        "id": slot_id,
        "label": label,
        "path": path,
        "volume": max(0, min(100, volume)),
        "shortcut": shortcut,
        "output_channel": output_channel,
        "send_to_micro": bool(raw.get("send_to_micro", False)),
        "auto_gain": auto_gain,
        "analyzed_path": analyzed_path,
        "trim_db": trim_db,
    }


def _ensure_unique_slot_ids(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixed: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    next_number = 1

    for index, raw in enumerate(slots):
        slot = _clean_slot(raw if isinstance(raw, dict) else {}, index)
        slot_id = str(slot.get("id", "") or "").strip()

        if not slot_id or slot_id in used_ids:
            while _slot_id(next_number - 1) in used_ids:
                next_number += 1

            slot_id = _slot_id(next_number - 1)
            slot["id"] = slot_id

            label = str(slot.get("label", "") or "").strip()
            if not label or re.fullmatch(r"SOUND\s+\d+", label, flags=re.IGNORECASE):
                slot["label"] = f"SOUND {next_number}"

        used_ids.add(slot_id)

        match = re.fullmatch(r"sb(\d+)", slot_id)
        if match:
            next_number = max(next_number, int(match.group(1)) + 1)

        fixed.append(slot)

    return fixed


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _run_pactl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=1.8)


def _sink_index_to_name() -> dict[str, str]:
    proc = _run_pactl(["list", "short", "sinks"])
    if proc.returncode != 0:
        return {}
    mapping: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            mapping[parts[0]] = parts[1]
    return mapping


def _sink_exists(name: str) -> bool:
    return name in set(_sink_index_to_name().values())


def _ensure_soundboard_bus() -> bool:
    if _sink_exists(SOUNDBOARD_BUS):
        return True

    proc = _run_pactl([
        "load-module",
        "module-null-sink",
        f"sink_name={SOUNDBOARD_BUS}",
        "sink_properties=device.description=🎛SOUNDBOARD media.name=K-Sound-Hub-Soundboard-Bus",
        "channels=2",
        "rate=48000",
    ])
    return proc.returncode == 0 or _sink_exists(SOUNDBOARD_BUS)


def _soundboard_monitor_module_ids() -> list[tuple[str, str]]:
    proc = _run_pactl(["list", "modules", "short"])
    if proc.returncode != 0:
        return []

    modules: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if "source=soundboard.monitor" not in line:
            continue
        if SOUNDBOARD_MONITOR_MEDIA_NAME not in line:
            continue

        parts = line.split(None, 2)
        if parts:
            modules.append((parts[0], line))

    return modules


def _ensure_soundboard_monitor_route(target_channel: str) -> bool:
    # Native micro/return path:
    # keep the soundboard bus available, but do NOT keep the old permanent
    # soundboard.monitor -> MEDIA/GAME/... loopback alive.
    #
    # That old route makes SOUNDBOARD appear stuck on MEDIA and can interfere
    # with the new native micro/return routing.
    #
    # Emergency override:
    #   KSH_SOUNDBOARD_MONITOR_ROUTE=1
    # restores the previous behavior.
    enabled = str(os.environ.get("KSH_SOUNDBOARD_MONITOR_ROUTE", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not enabled:
        for module_id, _line in _soundboard_monitor_module_ids():
            _run_pactl(["unload-module", module_id])
        return False

    target_channel = str(target_channel or "").strip().lower()
    if target_channel not in PLAYBACK_TARGETS:
        target_channel = "media"

    if not _ensure_soundboard_bus():
        return False

    if not _sink_exists(target_channel):
        return False

    wanted = f"sink={target_channel}"

    for _module_id, line in _soundboard_monitor_module_ids():
        if wanted in line:
            return True

    for module_id, _line in _soundboard_monitor_module_ids():
        _run_pactl(["unload-module", module_id])

    proc = _run_pactl([
        "load-module",
        "module-loopback",
        "source=soundboard.monitor",
        f"sink={target_channel}",
        "latency_msec=20",
        "source_dont_move=true",
        "sink_dont_move=true",
        f"sink_input_properties=media.name={SOUNDBOARD_MONITOR_MEDIA_NAME}",
    ])
    return proc.returncode == 0


def _current_process_sink_inputs() -> list[dict[str, str]]:
    proc = _run_pactl(["list", "sink-inputs"])
    if proc.returncode != 0:
        return []

    own_pid = str(os.getpid())
    sink_map = _sink_index_to_name()
    inputs: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    prop_re = re.compile(r'^\s*([^=]+?)\s*=\s*"(.*)"\s*$')

    def flush() -> None:
        if not current:
            return
        props = {k[5:]: v for k, v in current.items() if k.startswith("prop:")}
        if props.get("application.process.id") != own_pid:
            return
        media_name = props.get("media.name", "")
        if any(
            needle in media_name
            for needle in (
                "K-Sound Hub Return Mic",
                "K-Sound Hub Mic Physical",
                "K-Sound Hub Mic Send",
                "K-Sound Hub EQ",
            )
        ):
            return
        current["media_name"] = media_name
        current["sink_name"] = sink_map.get(current.get("sink_index", ""), "")
        inputs.append(dict(current))

    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("Sink Input #"):
            flush()
            current = {"id": line.split("#", 1)[1].strip(), "sink_index": ""}
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped.startswith("Sink: "):
            current["sink_index"] = stripped.split(":", 1)[1].strip()
            continue

        match = prop_re.match(line)
        if match:
            current[f"prop:{match.group(1).strip()}"] = match.group(2).strip()

    flush()
    return inputs


def _move_latest_soundboard_stream(target_channel: str) -> bool:
    target_channel = target_channel.strip().lower()
    valid_targets = set(PLAYBACK_TARGETS) | {SOUNDBOARD_BUS}
    if target_channel not in valid_targets or not _sink_exists(target_channel):
        return False

    candidates = [
        item
        for item in _current_process_sink_inputs()
        if item.get("sink_name") not in {target_channel, "micro_bus"}
    ]
    if not candidates:
        return False

    def sort_key(item: dict[str, str]) -> int:
        try:
            return int(item.get("id", "0"))
        except Exception:
            return 0

    stream = sorted(candidates, key=sort_key)[-1]
    proc = _run_pactl(["move-sink-input", stream["id"], target_channel])
    return proc.returncode == 0


def _device_haystack(device) -> str:
    try:
        raw_id = bytes(device.id()).decode("utf-8", errors="ignore")
    except Exception:
        raw_id = ""
    try:
        description = str(device.description())
    except Exception:
        description = ""
    return f"{raw_id} {description}".lower()


def _find_audio_output_device(*needles: str):
    try:
        devices = list(QMediaDevices.audioOutputs())
    except Exception:
        return None

    lowered = [needle.lower() for needle in needles if needle]
    for device in devices:
        haystack = _device_haystack(device)
        if all(needle in haystack for needle in lowered):
            return device

    return None


def _audio_output_for_sink_name(sink_name: str, parent) -> tuple[QAudioOutput, bool]:
    device = _find_audio_output_device(sink_name)
    if device is None:
        return QAudioOutput(parent), False

    try:
        return QAudioOutput(device, parent), True
    except TypeError:
        audio = QAudioOutput(parent)
        try:
            audio.setDevice(device)
            return audio, True
        except Exception:
            return audio, False


class SoundboardNoWheelSlider(NoWheelSlider):
    """Slider qui ne change pas au scroll, mais laisse le scroll remonter au panneau."""

    def wheelEvent(self, event) -> None:
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                bar = parent.verticalScrollBar()

                pixel_delta = event.pixelDelta().y()
                angle_delta = event.angleDelta().y()
                delta = pixel_delta if pixel_delta else angle_delta

                if delta:
                    bar.setValue(bar.value() - delta)
                    event.accept()
                    return

                break

            parent = parent.parent()

        event.ignore()


class SoundboardPadWidget(QFrame):
    changed = Signal()
    play_requested = Signal(str)
    move_requested = Signal(str, str)
    swap_requested = Signal(str, str)
    drag_started = Signal(str, int, int)
    drag_moved = Signal(str, int, int)
    drag_finished = Signal(str, int, int)
    edit_clicked = Signal(str)

    def __init__(self, slot: dict[str, Any], parent=None):
        super().__init__(parent)
        self.slot = slot
        self.auto_level_mode = False
        self._drag_start_pos = None
        self._custom_drag_active = False
        self._custom_drag_target = None
        self.setObjectName("soundboardPad")
        self.setMinimumWidth(230)
        self._edit_mode = False
        self._manual_drag_active = False

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self.label_edit = QLineEdit(str(slot.get("label", "SOUND")))
        self.label_edit.setAlignment(Qt.AlignLeft)
        self.label_edit.setCursorPosition(0)
        self.label_edit.setPlaceholderText("Sound name")
        self.label_edit.editingFinished.connect(self._commit_label)
        top.addWidget(self.label_edit, 1)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("soundPadPlay")
        self.play_btn.setMinimumWidth(44)
        self.play_btn.clicked.connect(lambda: self.play_requested.emit(str(self.slot.get("id", ""))))
        top.addWidget(self.play_btn)

        root.addLayout(top)

        self.move_controls = QWidget()
        move_layout = QHBoxLayout(self.move_controls)
        move_layout.setContentsMargins(0, 0, 0, 0)
        move_layout.setSpacing(6)

        for text, direction in (("↑", "up"), ("←", "left"), ("→", "right"), ("↓", "down")):
            button = QPushButton(text)
            button.setObjectName("soundPadMove")
            button.setToolTip(f"Move {direction}")
            button.clicked.connect(
                lambda _checked=False, value=direction: self.move_requested.emit(
                    str(self.slot.get("id", "")),
                    value,
                )
            )
            move_layout.addWidget(button)

        self.move_controls.setVisible(False)
        root.addWidget(self.move_controls)

        self.file_label = QLabel(self._path_label())
        self.file_label.setObjectName("mutedLabel")
        self.file_label.setWordWrap(True)
        root.addWidget(self.file_label)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(6)

        choose_btn = QPushButton("Choose")
        choose_btn.setObjectName("ghostButton")
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(choose_btn)

        self._clear_confirm_pending = False
        self._clear_confirm_timer = QTimer(self)
        self._clear_confirm_timer.setSingleShot(True)
        self._clear_confirm_timer.timeout.connect(self._reset_clear_confirm)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("soundPadClearButton")
        self.clear_btn.clicked.connect(self._clear_file)
        file_row.addWidget(self.clear_btn)

        root.addLayout(file_row)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(8)

        self.volume_mode_label = QLabel("Vol")
        self.volume_mode_label.setObjectName("mutedLabel")
        volume_row.addWidget(self.volume_mode_label)

        self.volume_slider = SoundboardNoWheelSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(slot.get("volume", 80)))
        self.volume_slider.valueChanged.connect(self._commit_volume)
        volume_row.addWidget(self.volume_slider, 1)

        self.volume_value = QLabel(f"{int(slot.get('volume', 80))}%")
        self.volume_value.setObjectName("mutedLabel")
        self.volume_value.setMinimumWidth(34)
        volume_row.addWidget(self.volume_value)

        root.addLayout(volume_row)

        route_row = QHBoxLayout()
        route_row.setContentsMargins(0, 0, 0, 0)
        route_row.setSpacing(8)

        route_label = QLabel("Hear")
        route_label.setObjectName("mutedLabel")
        route_row.addWidget(route_label)

        self.output_selector = MenuSelectorButton()
        self.output_selector.setObjectName("selectorButton")
        self.output_selector.set_items([item.upper() for item in PLAYBACK_TARGETS])
        self.output_selector.setCurrentText(str(slot.get("output_channel", "media")).upper())
        self.output_selector.currentTextChanged.connect(self._commit_output_channel)
        route_row.addWidget(self.output_selector, 1)

        self.micro_check = QCheckBox("MIC via channel")
        self.micro_check.setChecked(bool(slot.get("send_to_micro", False)))
        self.micro_check.toggled.connect(self._commit_send_to_micro)
        route_row.addWidget(self.micro_check)

        root.addLayout(route_row)

        self.shortcut_edit = QLineEdit(str(slot.get("shortcut", "")))
        self.shortcut_edit.setAlignment(Qt.AlignLeft)
        self.shortcut_edit.setCursorPosition(0)
        self.shortcut_edit.setPlaceholderText("App shortcut: e.g. Ctrl+Alt+1")
        self.shortcut_edit.editingFinished.connect(self._commit_shortcut)
        root.addWidget(self.shortcut_edit)

        def _pt(widget, fallback):
            size = widget.font().pointSizeF()
            if size <= 0:
                size = float(widget.font().pointSize() if widget.font().pointSize() > 0 else fallback)
            return float(size)

        self._font_bases = {
            "label_edit": _pt(self.label_edit, 10.0),
            "play_btn": _pt(self.play_btn, 10.0),
            "file_label": _pt(self.file_label, 9.0),
            "volume_mode_label": _pt(self.volume_mode_label, 9.0),
            "volume_value": _pt(self.volume_value, 9.0),
            "micro_check": _pt(self.micro_check, 9.0),
            "shortcut_edit": _pt(self.shortcut_edit, 9.0),
        }

        self._base_font_sizes: dict[QWidget, float] = {}
        for widget in [self, *self.findChildren(QWidget)]:
            font = widget.font()
            point_size = font.pointSizeF()
            if point_size <= 0:
                point_size = float(font.pointSize() if font.pointSize() > 0 else 10.0)
            self._base_font_sizes[widget] = point_size

    def set_pad_scale(self, scale_percent: int) -> None:
        try:
            value = int(scale_percent)
        except Exception:
            value = SOUNDBOARD_PAD_SCALE_DEFAULT

        value = max(SOUNDBOARD_PAD_SCALE_MIN, min(SOUNDBOARD_PAD_SCALE_MAX, value))
        card_factor = value / 100.0

        if card_factor < 1.0:
            font_factor = 1.0 - ((1.0 - card_factor) * 0.22)
        else:
            font_factor = 1.0 + ((card_factor - 1.0) * 0.16)

        self.setMinimumWidth(max(118, int(230 * card_factor)))

        margin = max(7, int(12 * max(card_factor, 0.72)))
        spacing = max(5, int(8 * max(card_factor, 0.78)))
        self._root_layout.setContentsMargins(margin, margin, margin, margin)
        self._root_layout.setSpacing(spacing)

        self.play_btn.setMinimumWidth(max(34, int(44 * max(card_factor, 0.78))))
        self.play_btn.setMinimumHeight(max(28, int(34 * max(card_factor, 0.82))))

        self.label_edit.setMinimumHeight(max(30, int(32 * max(card_factor, 0.90))))
        self.shortcut_edit.setMinimumHeight(max(26, int(30 * max(card_factor, 0.86))))
        self.file_label.setMinimumHeight(max(18, int(22 * max(card_factor, 0.86))))

        self._apply_font_size(self.label_edit, self._font_bases["label_edit"] * font_factor, 9.0, 15.5)
        self._apply_font_size(self.play_btn, self._font_bases["play_btn"] * font_factor, 9.0, 15.0)
        self._apply_font_size(self.file_label, self._font_bases["file_label"] * font_factor, 8.2, 13.5)
        self._apply_font_size(self.volume_mode_label, self._font_bases["volume_mode_label"] * font_factor, 8.0, 12.5)
        self._apply_font_size(self.volume_value, self._font_bases["volume_value"] * font_factor, 8.0, 12.5)
        self._apply_font_size(self.micro_check, self._font_bases["micro_check"] * font_factor, 8.0, 12.5)
        self._apply_font_size(self.shortcut_edit, self._font_bases["shortcut_edit"] * font_factor, 8.0, 12.0)

        self.label_edit.setAlignment(Qt.AlignLeft)
        self.label_edit.setCursorPosition(0)
        self.label_edit.deselect()

        self.shortcut_edit.setAlignment(Qt.AlignLeft)
        self.shortcut_edit.setCursorPosition(0)
        self.shortcut_edit.deselect()




    def _slot_key(self) -> str:
        return str(self.slot.get("id", ""))

    def _refresh_dynamic_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _set_visual_state(self, mode: str) -> None:
        mode = str(mode or "").strip().lower()
        self.setProperty("dragging", mode == "source")
        self.setProperty("dropTarget", mode == "target")
        self._refresh_dynamic_style()

    def _apply_font_size(self, widget, points: float, min_pt: float, max_pt: float) -> None:
        size = max(min_pt, min(max_pt, float(points)))
        font = widget.font()
        font.setPointSizeF(size)
        widget.setFont(font)
        widget.update()

    def _set_child_mouse_transparency(self, enabled: bool) -> None:
        # In edit mode, the whole card should behave as one drag handle.
        # Otherwise child widgets like QLineEdit/QPushButton can steal press/release
        # events and leave the manual drag stuck.
        for child in self.findChildren(QWidget):
            if child is not self:
                child.setAttribute(Qt.WA_TransparentForMouseEvents, bool(enabled))

    def _safe_release_manual_drag(self) -> None:
        try:
            self.releaseMouse()
        except Exception:
            pass

        self._manual_drag_active = False
        self._drag_start_pos = None
        self._set_visual_state("")

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = bool(enabled)
        self.setAcceptDrops(False)
        self.move_controls.setVisible(False)
        self._set_child_mouse_transparency(self._edit_mode)

        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(not self._edit_mode)

        self.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.ArrowCursor)
        self._safe_release_manual_drag()



    def _set_drop_target_visual(self, enabled: bool) -> None:
        self.setProperty("dropTarget", bool(enabled))

        if enabled:
            # Direct per-widget style because dynamic QSS properties are not
            # always repolished visibly enough on this QFrame with child widgets.
            self.setStyleSheet("""
                QFrame#soundboardPad {
                    border: 2px solid rgba(62, 216, 255, 1.00);
                    background-color: rgba(62, 216, 255, 0.32);
                    border-radius: 18px;
                }
            """)
        else:
            self.setStyleSheet("")

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _set_drag_source_visual(self, enabled: bool) -> None:
        self.setProperty("dragging", bool(enabled))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _pad_at_global_pos(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget is not None:
            if isinstance(widget, SoundboardPadWidget):
                return widget
            widget = widget.parentWidget() if hasattr(widget, "parentWidget") else None
        return None

    def _set_drag_status(self, text: str) -> None:
        dialog = self.parent()
        if dialog is not None and hasattr(dialog, "status_label"):
            dialog.status_label.setText(text)

    def _clear_custom_drag_visuals(self) -> None:
        self._set_drag_source_visual(False)

        target = getattr(self, "_custom_drag_target", None)
        if target is not None and target is not self:
            try:
                target._set_drop_target_visual(False)
            except Exception:
                pass

        self._custom_drag_target = None

    def mousePressEvent(self, event) -> None:
        if self._edit_mode and event.button() == Qt.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            event.accept()
            return

        super().mousePressEvent(event)



    def mouseMoveEvent(self, event) -> None:
        if not self._edit_mode or self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return

        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return

        if not self._manual_drag_active:
            if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < 8:
                return

            self._manual_drag_active = True
            self._set_visual_state("source")

            try:
                self.grabMouse(Qt.ClosedHandCursor)
            except Exception:
                pass

            global_pos = event.globalPosition().toPoint()
            self.drag_started.emit(self._slot_key(), global_pos.x(), global_pos.y())
            self.drag_moved.emit(self._slot_key(), global_pos.x(), global_pos.y())
            event.accept()
            return

        global_pos = event.globalPosition().toPoint()
        self.drag_moved.emit(self._slot_key(), global_pos.x(), global_pos.y())
        event.accept()



    def dragEnterEvent(self, event) -> None:
        event.ignore()



    def dragMoveEvent(self, event) -> None:
        event.ignore()



    def dragLeaveEvent(self, event) -> None:
        self._set_drop_target_visual(False)
        event.ignore()

    def dropEvent(self, event) -> None:
        event.ignore()



    def mouseReleaseEvent(self, event) -> None:
        if self._edit_mode and event.button() == Qt.LeftButton:
            was_dragging = bool(self._manual_drag_active)
            global_pos = event.globalPosition().toPoint()

            self._safe_release_manual_drag()

            if was_dragging:
                self.drag_finished.emit(self._slot_key(), global_pos.x(), global_pos.y())
            else:
                self.edit_clicked.emit(self._slot_key())

            event.accept()
            return

        super().mouseReleaseEvent(event)


    def _path_label(self) -> str:
        path = str(self.slot.get("path", "")).strip()
        if not path:
            return "No audio selected"
        return Path(path).name

    def _commit_label(self) -> None:
        self.slot["label"] = self.label_edit.text().strip() or str(self.slot.get("id", "SOUND"))
        self.label_edit.setCursorPosition(0)
        self.changed.emit()


    def _format_trim_db(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.0f} dB"

    def set_auto_level_mode(self, enabled: bool) -> None:
        self.auto_level_mode = bool(enabled)

        self.volume_slider.blockSignals(True)
        try:
            if self.auto_level_mode:
                trim = float(self.slot.get("trim_db", SOUNDBOARD_TRIM_DB_DEFAULT))
                trim = max(SOUNDBOARD_TRIM_DB_MIN, min(SOUNDBOARD_TRIM_DB_MAX, trim))

                self.volume_mode_label.setText("Trim")
                self.volume_slider.setRange(SOUNDBOARD_TRIM_DB_MIN, SOUNDBOARD_TRIM_DB_MAX)
                self.volume_slider.setValue(int(round(trim)))
                self.volume_value.setText(self._format_trim_db(trim))
            else:
                volume = int(self.slot.get("volume", 80))

                self.volume_mode_label.setText("Vol")
                self.volume_slider.setRange(0, 100)
                self.volume_slider.setValue(max(0, min(100, volume)))
                self.volume_value.setText(f"{max(0, min(100, volume))}%")
        finally:
            self.volume_slider.blockSignals(False)

    def _commit_volume(self, value: int) -> None:
        if self.auto_level_mode:
            trim = max(SOUNDBOARD_TRIM_DB_MIN, min(SOUNDBOARD_TRIM_DB_MAX, float(value)))
            self.slot["trim_db"] = trim
            self.volume_value.setText(self._format_trim_db(trim))
        else:
            volume = max(0, min(100, int(value)))
            self.slot["volume"] = volume
            self.volume_value.setText(f"{volume}%")

        self.changed.emit()

    def _commit_output_channel(self, value: str) -> None:
        target = str(value or "MEDIA").strip().lower()
        self.slot["output_channel"] = target if target in PLAYBACK_TARGETS else "media"
        self.changed.emit()

    def _commit_send_to_micro(self, checked: bool) -> None:
        self.slot["send_to_micro"] = bool(checked)
        self.changed.emit()

    def _commit_shortcut(self) -> None:
        self.slot["shortcut"] = self.shortcut_edit.text().strip()
        self.shortcut_edit.setCursorPosition(0)
        self.changed.emit()


    def _choose_file(self) -> None:
        current = str(self.slot.get("path", "") or "")

        start_candidates: list[Path] = []
        if current:
            start_candidates.append(Path(current).expanduser().parent)

        try:
            last_dir = SOUNDBOARD_LAST_DIR_PATH.read_text(encoding="utf-8").strip()
            if last_dir:
                start_candidates.append(Path(last_dir).expanduser())
        except Exception:
            pass

        start_candidates.append(Path.home())

        start_dir = Path.home()
        for candidate in start_candidates:
            try:
                if candidate.is_dir():
                    start_dir = candidate
                    break
            except Exception:
                continue

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a sound",
            str(start_dir),
            SUPPORTED_AUDIO_FILTER,
        )
        if not filename:
            return

        selected_path = Path(filename).expanduser()

        try:
            SOUNDBOARD_LAST_DIR_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOUNDBOARD_LAST_DIR_PATH.write_text(str(selected_path.parent) + "\n", encoding="utf-8")
            SOUNDBOARD_LAST_DIR_PATH.chmod(0o600)
        except Exception:
            pass

        self.slot["path"] = filename

        current_label = self.label_edit.text().strip()
        if not current_label or current_label.startswith("SOUND "):
            auto_label = selected_path.stem.replace("_", " ").replace("-", " ").strip()
            if auto_label:
                self.slot["label"] = auto_label
                self.label_edit.setText(auto_label)
                self.label_edit.setCursorPosition(0)

        self.file_label.setText(self._path_label())
        self.changed.emit()


    def _reset_clear_confirm(self) -> None:
        self._clear_confirm_pending = False
        if hasattr(self, "clear_btn"):
            self.clear_btn.setText("Clear")
            self.clear_btn.setToolTip("")
            self.clear_btn.setProperty("clearConfirm", False)
            self.clear_btn.style().unpolish(self.clear_btn)
            self.clear_btn.style().polish(self.clear_btn)

    def _clear_file(self) -> None:
        current = str(self.slot.get("path", "") or "").strip()

        if not current:
            self._reset_clear_confirm()
            return

        if not self._clear_confirm_pending:
            self._clear_confirm_pending = True
            self.clear_btn.setText("Confirm")
            self.clear_btn.setToolTip("Click again within 4 seconds to remove this sound")
            self.clear_btn.setProperty("clearConfirm", True)
            self.clear_btn.style().unpolish(self.clear_btn)
            self.clear_btn.style().polish(self.clear_btn)
            self._clear_confirm_timer.start(4000)
            return

        self._clear_confirm_timer.stop()
        self._reset_clear_confirm()

        self.slot["path"] = ""

        for cache_key in ("auto_gain", "analyzed_path", "processed_path"):
            self.slot.pop(cache_key, None)

        self.file_label.setText(self._path_label())
        self.changed.emit()



class SoundboardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("K-Sound Hub — Soundboard")
        self.resize(1120, 720)
        install_window_geometry(self, "soundboard", default_size=(1120, 720))

        self.slots = self._load_slots()
        self.global_volume = self._load_global_volume()
        self.auto_level_enabled = self._load_auto_level_enabled()
        self.pad_scale = self._load_pad_scale()
        self.pad_widgets: list[SoundboardPadWidget] = []
        self._players: dict[str, tuple[QMediaPlayer, QAudioOutput]] = {}
        self._player_source_paths: dict[str, str] = {}
        self._soundboard_bus_ready = False
        self._soundboard_monitor_routes_ready: set[str] = set()
        self._shortcuts: list[QShortcut] = []
        self.edit_mode = False
        self._drag_source_id = ""
        self._drag_target_id = ""
        self._selected_slot_id = ""
        self._rebuilding_grid = False
        self._last_grid_columns = 0
        self._click_drop_source_id = ""
        self._selected_delete_id = ""
        self._delete_confirm_pending = False
        self._delete_confirm_timer = QTimer(self)
        self._delete_confirm_timer.setSingleShot(True)
        self._delete_confirm_timer.timeout.connect(self._reset_delete_button_confirm)

        self._cache_building_keys: set[str] = set()
        self._cache_warm_thread_active = False
        self._cache_warmup_timer = QTimer(self)
        self._cache_warmup_timer.setSingleShot(True)
        self._cache_warmup_timer.timeout.connect(self._start_background_soundboard_cache)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("sectionCard")

        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(4)

        title = QLabel("SOUNDBOARD")
        title.setObjectName("pageTitle")
        header_layout.addWidget(title)

        subtitle = QLabel(
            "Audio pads with independent volume. Sound always plays through the SOUNDBOARD bus. "
            "'Hear' selects where you monitor it. For mic send: MICRO → Apps → + → SOUNDBOARD."
        )
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        root.addWidget(header)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedLabel")

        self.scroll = QScrollArea()
        scroll = self.scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setObjectName("scrollViewport")

        self.grid_host = QWidget()
        host = self.grid_host
        host.setObjectName("columnsHost")

        for drop_widget in (scroll, scroll.viewport(), host):
            drop_widget.setAcceptDrops(False)
            drop_widget.installEventFilter(self)

        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)

        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName("footerBar")

        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 6, 10, 6)
        footer_layout.setSpacing(8)
        footer_layout.addWidget(self.status_label, 1)

        self.auto_level_check = QCheckBox("Auto level")
        self.auto_level_check.setObjectName("soundboardSwitch")
        self.auto_level_check.setChecked(bool(self.auto_level_enabled))
        self.auto_level_check.toggled.connect(self._on_auto_level_changed)
        footer_layout.addWidget(self.auto_level_check)

        global_label = QLabel("🔊")
        global_label.setObjectName("mutedLabel")
        global_label.setToolTip("Volume soundboard")
        footer_layout.addWidget(global_label)

        self.global_volume_slider = SoundboardNoWheelSlider(Qt.Horizontal)
        self.global_volume_slider.setRange(0, 100)
        self.global_volume_slider.setMinimumWidth(55)
        self.global_volume_slider.setMaximumWidth(130)
        self.global_volume_slider.setValue(int(self.global_volume))
        self.global_volume_slider.valueChanged.connect(self._on_global_volume_changed)
        footer_layout.addWidget(self.global_volume_slider)

        self.global_volume_value = QLabel(f"{int(self.global_volume)}%")
        self.global_volume_value.setObjectName("mutedLabel")
        self.global_volume_value.setMinimumWidth(38)
        footer_layout.addWidget(self.global_volume_value)

        self.scale_btn = QPushButton("Scale")
        self.scale_btn.setObjectName("soundboardScaleButton")
        self.scale_btn.setCheckable(True)
        self.scale_btn.setMinimumWidth(58)
        self.scale_btn.setMaximumWidth(78)
        self.scale_btn.toggled.connect(self._on_scale_panel_toggled)
        footer_layout.addWidget(self.scale_btn)

        self.scale_label = QLabel("Scale")
        self.scale_label.setObjectName("mutedLabel")
        footer_layout.addWidget(self.scale_label)

        self.pad_scale_slider = SoundboardNoWheelSlider(Qt.Horizontal)
        self.pad_scale_slider.setRange(SOUNDBOARD_PAD_SCALE_MIN, SOUNDBOARD_PAD_SCALE_MAX)
        self.pad_scale_slider.setMinimumWidth(0)
        self.pad_scale_slider.setMaximumWidth(0)
        self.pad_scale_slider.setValue(int(self.pad_scale))
        self.pad_scale_slider.setTracking(False)
        self.pad_scale_slider.sliderMoved.connect(self._on_pad_scale_preview)
        self.pad_scale_slider.valueChanged.connect(self._on_pad_scale_changed)
        footer_layout.addWidget(self.pad_scale_slider)

        self.pad_scale_value = QLabel(f"{int(self.pad_scale)}%")
        self.pad_scale_value.setObjectName("mutedLabel")
        self.pad_scale_value.setMinimumWidth(42)
        footer_layout.addWidget(self.pad_scale_value)

        self.scale_options_widget = QWidget()
        self.scale_options_widget.setObjectName("scaleOptionsWidget")
        scale_options_layout = QHBoxLayout(self.scale_options_widget)
        scale_options_layout.setContentsMargins(0, 0, 0, 0)
        scale_options_layout.setSpacing(4)

        self.scale_option_buttons: dict[int, QPushButton] = {}
        for label, value in (
            ("0.5×", 50),
            ("0.75×", 75),
            ("1×", 100),
            ("1.25×", 125),
            ("1.5×", 150),
            ("2×", 200),
        ):
            button = QPushButton(label)
            button.setObjectName("soundboardScaleOption")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.clicked.connect(lambda _checked=False, v=value: self._on_pad_scale_option(v))
            scale_options_layout.addWidget(button)
            self.scale_option_buttons[value] = button

        footer_layout.addWidget(self.scale_options_widget)

        for scale_widget in (
            self.scale_label,
            self.pad_scale_slider,
            self.pad_scale_value,
            self.scale_options_widget,
        ):
            scale_widget.setVisible(False)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setObjectName("soundboardEditButton")
        self.edit_btn.setCheckable(True)
        self.edit_btn.setMinimumWidth(56)
        self.edit_btn.setMaximumWidth(72)
        self.edit_btn.toggled.connect(self._on_edit_toggled)
        footer_layout.addWidget(self.edit_btn)

        self.delete_selected_btn = QPushButton("Delete")
        self.delete_selected_btn.setObjectName("soundboardDeleteButton")
        self.delete_selected_btn.setVisible(False)
        self.delete_selected_btn.clicked.connect(self.delete_selected_slot)
        footer_layout.addWidget(self.delete_selected_btn)

        add_btn = QPushButton("+1 pad")
        add_btn.setObjectName("ghostButton")
        add_btn.clicked.connect(self.add_one_slot)
        footer_layout.addWidget(add_btn)

        pair_btn = QPushButton("Pair Android")
        pair_btn.setObjectName("ghostButton")
        pair_btn.clicked.connect(self.create_android_pairing)
        footer_layout.addWidget(pair_btn)

        stop_all_btn = QPushButton("Stop all")
        stop_all_btn.setObjectName("ghostButton")
        stop_all_btn.clicked.connect(self.stop_all)
        footer_layout.addWidget(stop_all_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("ghostButton")
        save_btn.clicked.connect(self.save)
        footer_layout.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("ghostButton")
        close_btn.clicked.connect(self.close)
        footer_layout.addWidget(close_btn)

        root.addWidget(footer)

        footer.setMinimumWidth(0)
        footer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        for footer_child in footer.findChildren(QWidget):
            footer_child.setMinimumWidth(0)

        self.setMinimumSize(260, 320)

        self.setStyleSheet(
            """
            QFrame#soundboardPad {
                background: rgba(16, 22, 34, 238);
                border: 1px solid rgba(62, 216, 255, 68);
                border-radius: 18px;
            }
            QFrame#soundboardPad:hover {
                border: 1px solid rgba(255, 92, 199, 84);
            }
            QFrame#soundboardPad[dragging="true"] {
                opacity: 0.65;
                border-color: rgba(255, 92, 199, 0.95);
                background: rgba(255, 92, 199, 0.10);
            }
            QFrame#soundboardPad[dropTarget="true"] {
                border: 2px solid rgba(62, 216, 255, 1.00);
                background: rgba(62, 216, 255, 0.32);
            }
            QPushButton#soundPadPlay {
                font-size: 18px;
                font-weight: 900;
                border-radius: 13px;
                padding: 6px 10px;
            }
            QPushButton#soundPadMove {
                font-size: 14px;
                font-weight: 900;
                border-radius: 10px;
                padding: 4px 8px;
            }
            QPushButton#soundboardEditButton {
                border: 1px solid rgba(62, 216, 255, 0.55);
                border-radius: 10px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 900;
                color: rgba(236, 247, 255, 230);
                background: rgba(12, 18, 30, 0.82);
            }
            QPushButton#soundboardEditButton:checked {
                border: 1px solid rgba(255, 92, 199, 1.00);
                color: #071018;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(62, 216, 255, 0.95),
                    stop:1 rgba(255, 92, 199, 0.95)
                );
            }
            QPushButton#soundboardScaleButton {
                border: 1px solid rgba(62, 216, 255, 0.55);
                border-radius: 10px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 900;
                color: rgba(236, 247, 255, 230);
                background: rgba(12, 18, 30, 0.82);
            }
            QPushButton#soundboardScaleButton:checked {
                border: 1px solid rgba(62, 216, 255, 1.00);
                color: #071018;
                background: rgba(62, 216, 255, 0.90);
            }
            QPushButton#soundPadClearButton[clearConfirm="true"] {
                border: 2px solid rgba(255, 78, 78, 1.00);
                color: rgba(255, 245, 245, 245);
                background: rgba(190, 26, 42, 0.92);
                font-weight: 900;
            }
            QPushButton#soundboardDeleteButton {
                border: 1px solid rgba(255, 78, 78, 0.70);
                border-radius: 10px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 900;
                color: rgba(255, 235, 235, 245);
                background: rgba(70, 12, 18, 0.88);
            }
            QPushButton#soundboardDeleteButton:hover {
                border: 2px solid rgba(255, 78, 78, 1.00);
                background: rgba(145, 24, 36, 0.92);
            }
            QPushButton[clearConfirm="true"] {
                border: 2px solid rgba(255, 82, 102, 1.00);
                color: #fff4f6;
                background: rgba(180, 28, 48, 0.92);
            }
            QPushButton#soundboardDeleteButton {
                border: 1px solid rgba(255, 92, 199, 0.55);
                border-radius: 10px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 900;
                color: rgba(236, 247, 255, 230);
                background: rgba(35, 9, 28, 0.82);
            }
            QPushButton#soundboardDeleteButton:disabled {
                color: rgba(147, 164, 184, 130);
                border: 1px solid rgba(147, 164, 184, 65);
                background: rgba(12, 18, 30, 0.55);
            }
            QPushButton#soundboardDeleteButton[deleteConfirm="true"] {
                border: 2px solid rgba(255, 82, 102, 1.00);
                color: #fff4f6;
                background: rgba(180, 28, 48, 0.92);
            }
            QCheckBox#soundboardSwitch {
                spacing: 8px;
                font-weight: 800;
                color: rgba(236, 247, 255, 220);
            }
            QCheckBox#soundboardSwitch::indicator {
                width: 38px;
                height: 20px;
                border-radius: 10px;
                border: 1px solid rgba(147, 164, 184, 105);
                background: rgba(50, 60, 78, 190);
            }
            QCheckBox#soundboardSwitch::indicator:checked {
                border: 1px solid rgba(62, 216, 255, 160);
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(62, 216, 255, 210),
                    stop:1 rgba(255, 92, 199, 210)
                );
            }
            /* KSH compact footer controls */
            QPushButton#soundboardEditButton,
            QPushButton#soundboardScaleButton,
            QPushButton#soundboardDeleteButton {
                min-height: 24px;
                max-height: 24px;
                padding: 2px 8px;
                border-radius: 9px;
                font-size: 10px;
                font-weight: 800;
            }
            QPushButton#soundboardEditButton:checked {
                border: 2px solid rgba(255, 92, 199, 0.95);
                background: rgba(255, 92, 199, 0.22);
                color: rgba(255, 240, 250, 245);
            }
            QPushButton#soundboardScaleButton:checked {
                border: 2px solid rgba(62, 216, 255, 0.95);
                background: rgba(62, 216, 255, 0.30);
                color: rgba(236, 247, 255, 245);
            }
            QPushButton#soundboardScaleOption {
                min-height: 24px;
                max-height: 24px;
                padding: 2px 7px;
                border-radius: 9px;
                font-size: 10px;
                font-weight: 800;
                border: 1px solid rgba(62, 216, 255, 0.45);
                background: rgba(12, 18, 30, 0.82);
                color: rgba(236, 247, 255, 220);
            }
            QPushButton#soundboardScaleOption:checked {
                border: 2px solid rgba(62, 216, 255, 0.95);
                background: rgba(62, 216, 255, 0.30);
                color: rgba(236, 247, 255, 245);
            }
            QWidget#scaleOptionsWidget {
                background: transparent;
            }
            QCheckBox {
                background: transparent;
                font-size: 11px;
            }
            """
        )

        self._rebuild_grid()
        self._rebuild_shortcuts()
        QTimer.singleShot(450, self._preload_soundboard_players)
        QTimer.singleShot(900, self._start_background_soundboard_cache)
        QTimer.singleShot(2600, self._preload_soundboard_players)
        QTimer.singleShot(6500, self._preload_soundboard_players)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

        if getattr(self, "_rebuilding_grid", False):
            return

        try:
            columns = self._columns_for_pad_scale()
        except Exception:
            return

        if columns != getattr(self, "_last_grid_columns", 0):
            QTimer.singleShot(0, self._rebuild_grid)

    def _load_slots(self) -> list[dict[str, Any]]:
        if not SOUNDBOARD_PATH.is_file():
            return _default_slots()

        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            return _default_slots()

        raw_slots = data.get("slots", []) if isinstance(data, dict) else []
        if not isinstance(raw_slots, list) or not raw_slots:
            return _default_slots()

        return _ensure_unique_slot_ids(raw_slots)

    def save(self) -> None:
        self.slots = _ensure_unique_slot_ids(self.slots)
        SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOUNDBOARD_PATH.write_text(
            json.dumps(
                {
                    "global_volume": int(getattr(self, "global_volume", SOUNDBOARD_GLOBAL_VOLUME_DEFAULT)),
                    "auto_level_enabled": bool(getattr(self, "auto_level_enabled", SOUNDBOARD_AUTO_LEVEL_DEFAULT)),
                    "pad_scale": int(getattr(self, "pad_scale", SOUNDBOARD_PAD_SCALE_DEFAULT)),
                    "slots": self.slots,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.status_label.setText(f"Saved: {SOUNDBOARD_PATH}")
        self._rebuild_shortcuts()

        timer = getattr(self, "_cache_warmup_timer", None)
        if timer is not None and bool(getattr(self, "auto_level_enabled", False)):
            timer.start(700)

    def add_one_slot(self) -> None:
        self.slots = _ensure_unique_slot_ids(self.slots)
        self.slots.append(_default_slot_number(_next_slot_number(self.slots)))
        self._rebuild_grid()
        self.save()

    def add_four_slots(self) -> None:
        # Kept as a compatibility wrapper for old calls; the UI now adds one pad.
        self.add_one_slot()

    def _columns_for_pad_scale(self) -> int:
        try:
            scale = int(getattr(self, "pad_scale", SOUNDBOARD_PAD_SCALE_DEFAULT))
        except Exception:
            scale = SOUNDBOARD_PAD_SCALE_DEFAULT

        card_factor = max(0.5, min(2.0, scale / 100.0))
        target_width = max(150, int(230 * card_factor))

        viewport_width = 0
        scroll = getattr(self, "scroll", None)
        if scroll is not None:
            try:
                viewport_width = int(scroll.viewport().width())
            except Exception:
                viewport_width = 0

        if viewport_width <= 0:
            return 4

        if scale >= 175:
            max_columns = 2
        elif scale >= 135:
            max_columns = 3
        elif scale <= 60:
            max_columns = 6
        elif scale <= 85:
            max_columns = 5
        else:
            max_columns = 4

        columns_by_width = max(1, viewport_width // target_width)
        return max(1, min(max_columns, columns_by_width))



    def _rebuild_grid(self) -> None:
        if getattr(self, "_rebuilding_grid", False):
            return

        self._rebuilding_grid = True
        try:
            while self.grid.count():
                item = self.grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            self.pad_widgets.clear()

            columns = self._columns_for_pad_scale()
            self._last_grid_columns = columns

            for index, slot in enumerate(self.slots):
                pad = SoundboardPadWidget(slot, self)
                pad.set_auto_level_mode(self.auto_level_enabled)
                pad.changed.connect(self.save)
                pad.play_requested.connect(self.play_slot)
                pad.move_requested.connect(self.move_slot_by_key)
                pad.swap_requested.connect(self.swap_slots_by_keys)
                pad.drag_started.connect(self._on_pad_drag_started)
                pad.drag_moved.connect(self._on_pad_drag_moved)
                pad.drag_finished.connect(self._on_pad_drag_finished)
                pad.edit_clicked.connect(self._on_pad_edit_clicked)
                pad.set_edit_mode(self.edit_mode)
                pad.set_pad_scale(self.pad_scale)
                self.pad_widgets.append(pad)
                self.grid.addWidget(pad, index // columns, index % columns)

            self.grid.setRowStretch((len(self.slots) + columns - 1) // columns, 1)
            self._apply_edit_selection_visuals()
        finally:
            self._rebuilding_grid = False



    def eventFilter(self, watched, event) -> bool:
        if (
            getattr(self, "edit_mode", False)
            and event.type() in {QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop}
            and hasattr(event, "mimeData")
            and event.mimeData().hasFormat("application/x-ksound-soundboard-slot")
        ):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return True

        return super().eventFilter(watched, event)

    def _pad_by_slot_id(self, slot_id: str):
        slot_id = str(slot_id or "").strip()
        for pad in self.pad_widgets:
            if str(pad.slot.get("id", "")) == slot_id:
                return pad
        return None

    def _clear_pad_drag_visuals(self) -> None:
        for pad in self.pad_widgets:
            try:
                pad._set_visual_state("")
            except Exception:
                pass

    def _find_target_pad_from_global(self, x: int, y: int):
        widget = QApplication.widgetAt(QPoint(int(x), int(y)))
        while widget is not None:
            if isinstance(widget, SoundboardPadWidget):
                return widget
            widget = widget.parentWidget()
        return None

    def _apply_edit_selection_visuals(self) -> None:
        selected_id = str(getattr(self, "_selected_slot_id", "") or "").strip()

        for pad in getattr(self, "pad_widgets", []):
            try:
                slot_id = str(pad.slot.get("id", "") or "").strip()
                pad._set_drag_source_visual(bool(getattr(self, "edit_mode", False) and selected_id and slot_id == selected_id))
            except Exception:
                pass

        self._update_delete_button_state()



    def _set_edit_selection(self, slot_id: str) -> None:
        self._selected_slot_id = str(slot_id or "").strip()
        self._reset_delete_button_confirm()
        self._apply_edit_selection_visuals()



    def _update_delete_button_state(self) -> None:
        button = getattr(self, "delete_selected_btn", None)
        if button is None:
            return

        selected_id = str(getattr(self, "_selected_slot_id", "") or "").strip()
        visible = bool(getattr(self, "edit_mode", False) and selected_id)

        button.setVisible(visible)
        button.setEnabled(visible)
        button.setText("Delete")
        button.setProperty("deleteConfirm", False)
        button.style().unpolish(button)
        button.style().polish(button)



    def _on_pad_edit_clicked(self, slot_id: str) -> None:
        if not self.edit_mode:
            return

        slot_id = str(slot_id or "").strip()
        if not slot_id:
            return

        current = str(getattr(self, "_selected_slot_id", "") or "").strip()

        if not current:
            self._set_edit_selection(slot_id)
            self.status_label.setText(f"Selected {slot_id}. Click another pad to swap, or Delete to remove it.")
            return

        if current == slot_id:
            self._set_edit_selection("")
            self.status_label.setText("Selection cleared")
            return

        source_id = current
        self._set_edit_selection("")
        self.swap_slots_by_keys(source_id, slot_id)



    def _reset_delete_button_confirm(self) -> None:
        self._delete_confirm_pending = False

        timer = getattr(self, "_delete_confirm_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        button = getattr(self, "delete_selected_btn", None)
        if button is not None:
            button.setText("Delete")
            button.setProperty("deleteConfirm", False)
            button.setEnabled(bool(getattr(self, "edit_mode", False) and getattr(self, "_selected_slot_id", "")))
            button.style().unpolish(button)
            button.style().polish(button)



    def delete_selected_slot(self) -> bool:
        if not self.edit_mode:
            return False

        selected_id = str(getattr(self, "_selected_slot_id", "") or "").strip()
        if not selected_id:
            self.status_label.setText("Select a pad first")
            return False

        index = next((i for i, item in enumerate(self.slots) if str(item.get("id", "")) == selected_id), -1)
        if index < 0:
            self._set_edit_selection("")
            self.status_label.setText("Selected pad not found")
            return False

        removed = self.slots.pop(index)
        label = str(removed.get("label", selected_id) or selected_id)

        self._set_edit_selection("")
        self._rebuild_grid()
        self.save()
        self.status_label.setText(f"Deleted {label}")
        return True



    def _on_pad_drag_started(self, source_id: str, x: int, y: int) -> None:
        if not self.edit_mode:
            return

        self._drag_source_id = str(source_id or "").strip()
        self._drag_target_id = ""
        self._clear_pad_drag_visuals()

        source_pad = self._pad_by_slot_id(self._drag_source_id)
        if source_pad is not None:
            source_pad._set_visual_state("source")

        self._on_pad_drag_moved(source_id, x, y)

    def _on_pad_drag_moved(self, source_id: str, x: int, y: int) -> None:
        if not self.edit_mode:
            return

        source_id = str(source_id or "").strip()
        if not source_id or source_id != self._drag_source_id:
            return

        source_pad = self._pad_by_slot_id(source_id)
        if source_pad is None:
            return

        target_pad = self._find_target_pad_from_global(x, y)

        self._clear_pad_drag_visuals()
        source_pad._set_visual_state("source")

        if target_pad is not None:
            target_id = str(target_pad.slot.get("id", "")).strip()
            if target_id and target_id != source_id:
                target_pad._set_visual_state("target")
                self._drag_target_id = target_id
                self.status_label.setText(f"Move {source_id} → {target_id}")
                return

        self._drag_target_id = ""
        self.status_label.setText(f"Moving {source_id}")

    def _on_pad_drag_finished(self, source_id: str, x: int, y: int) -> None:
        source_id = str(source_id or "").strip()

        if not self.edit_mode or not source_id:
            self._clear_pad_drag_visuals()
            self._drag_source_id = ""
            self._drag_target_id = ""
            return

        target_pad = self._find_target_pad_from_global(x, y)
        target_id = str(target_pad.slot.get("id", "")).strip() if target_pad is not None else self._drag_target_id

        self._clear_pad_drag_visuals()
        self._drag_source_id = ""
        self._drag_target_id = ""

        if target_id and target_id != source_id:
            self.swap_slots_by_keys(source_id, target_id)
        else:
            self.status_label.setText("Edit mode: drag a pad onto another")


    def _on_edit_toggled(self, checked: bool) -> None:
        self.edit_mode = bool(checked)
        self._drag_source_id = ""
        self._drag_target_id = ""
        self._click_drop_source_id = ""
        self._selected_delete_id = ""
        self._delete_confirm_timer.stop()
        self._reset_delete_button_confirm()
        self._clear_pad_drag_visuals()

        for pad in self.pad_widgets:
            try:
                pad._safe_release_manual_drag()
            except Exception:
                pass
            pad.set_edit_mode(self.edit_mode)

        self._update_delete_button_state()

        self.status_label.setText(
            "Edit mode: drag, click-to-drop, or select a pad to delete"
            if self.edit_mode
            else "Edit mode: OFF"
        )



    def swap_slots_by_keys(self, source_id: str, target_id: str) -> bool:
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()

        source_index = next((i for i, item in enumerate(self.slots) if str(item.get("id", "")) == source_id), -1)
        target_index = next((i for i, item in enumerate(self.slots) if str(item.get("id", "")) == target_id), -1)

        if source_index < 0 or target_index < 0 or source_index == target_index:
            self.status_label.setText("Move unavailable")
            return False

        self.slots[source_index], self.slots[target_index] = self.slots[target_index], self.slots[source_index]
        self._rebuild_grid()
        self.save()
        self.status_label.setText(f"Moved {source_id} ↔ {target_id}")
        return True

    def reorder_slots_by_ids(self, order) -> bool:
        if not isinstance(order, list):
            self.status_label.setText("Invalid soundboard order")
            return False

        by_id = {str(slot.get("id", "")): slot for slot in self.slots}
        used: set[str] = set()
        reordered: list[dict[str, Any]] = []

        for raw_id in order:
            slot_id = str(raw_id or "").strip()
            if slot_id and slot_id in by_id and slot_id not in used:
                reordered.append(by_id[slot_id])
                used.add(slot_id)

        for slot in self.slots:
            slot_id = str(slot.get("id", ""))
            if slot_id not in used:
                reordered.append(slot)

        if len(reordered) != len(self.slots):
            self.status_label.setText("Incomplete soundboard order")
            return False

        old_order = [str(slot.get("id", "")) for slot in self.slots]
        new_order = [str(slot.get("id", "")) for slot in reordered]
        if old_order == new_order:
            return True

        self.slots = reordered
        self._rebuild_grid()
        self.save()
        self.status_label.setText("Soundboard order saved")
        return True

    def move_slot_by_key(self, slot_id: str, direction: str) -> bool:
        slot_id = str(slot_id or "").strip()
        direction = str(direction or "").strip().lower()
        columns = self._columns_for_pad_scale()

        index = next((i for i, item in enumerate(self.slots) if str(item.get("id", "")) == slot_id), -1)
        if index < 0:
            self.status_label.setText(f"Slot not found: {slot_id}")
            return False

        column = index % columns
        target = -1

        if direction == "left" and column > 0:
            target = index - 1
        elif direction == "right" and column < columns - 1 and index + 1 < len(self.slots):
            target = index + 1
        elif direction == "up" and index - columns >= 0:
            target = index - columns
        elif direction == "down" and index + columns < len(self.slots):
            target = index + columns

        if target < 0 or target >= len(self.slots):
            self.status_label.setText("Move unavailable")
            return False

        self.slots[index], self.slots[target] = self.slots[target], self.slots[index]
        self._rebuild_grid()
        self.save()
        self.status_label.setText(f"Moved {slot_id}: {direction}")
        return True

    def create_android_pairing(self) -> None:
        pin = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = time.time() + SOUNDBOARD_PAIRING_TTL_SECONDS

        SOUNDBOARD_PAIRING_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOUNDBOARD_PAIRING_PATH.write_text(
            json.dumps(
                {
                    "pin": pin,
                    "expires_at": expires_at,
                    "created_at": time.time(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        try:
            SOUNDBOARD_PAIRING_PATH.chmod(0o600)
        except Exception:
            pass

        self.status_label.setText(f"Android pairing code: {pin}")

        QMessageBox.information(
            self,
            "Pair Android",
            (
                "Code Android :\n\n"
                f"{pin}\n\n"
                "Expire dans 5 minutes.\n\n"
                "Ouvre l'app Android K-Sound Soundboard, laisse-la trouver le PC, "
                "puis entre ce code."
            ),
        )

    def _load_global_volume(self) -> int:
        if not SOUNDBOARD_PATH.is_file():
            return SOUNDBOARD_GLOBAL_VOLUME_DEFAULT

        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            value = int(data.get("global_volume", SOUNDBOARD_GLOBAL_VOLUME_DEFAULT))
        except Exception:
            value = SOUNDBOARD_GLOBAL_VOLUME_DEFAULT

        return max(0, min(100, value))

    def _load_auto_level_enabled(self) -> bool:
        if not SOUNDBOARD_PATH.is_file():
            return SOUNDBOARD_AUTO_LEVEL_DEFAULT

        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            return bool(data.get("auto_level_enabled", SOUNDBOARD_AUTO_LEVEL_DEFAULT))
        except Exception:
            return SOUNDBOARD_AUTO_LEVEL_DEFAULT

    def _load_pad_scale(self) -> int:
        if not SOUNDBOARD_PATH.is_file():
            return SOUNDBOARD_PAD_SCALE_DEFAULT

        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            value = int(data.get("pad_scale", SOUNDBOARD_PAD_SCALE_DEFAULT))
        except Exception:
            return SOUNDBOARD_PAD_SCALE_DEFAULT

        return max(SOUNDBOARD_PAD_SCALE_MIN, min(SOUNDBOARD_PAD_SCALE_MAX, value))

    def set_global_volume(self, value) -> None:
        try:
            volume = int(value)
        except Exception:
            return

        self.global_volume = max(0, min(100, volume))

        if hasattr(self, "global_volume_slider") and self.global_volume_slider.value() != self.global_volume:
            self.global_volume_slider.blockSignals(True)
            self.global_volume_slider.setValue(self.global_volume)
            self.global_volume_slider.blockSignals(False)

        if hasattr(self, "global_volume_value"):
            self.global_volume_value.setText(f"{int(self.global_volume)}%")

        self.save()

    def _update_scale_option_buttons(self) -> None:
        current = int(getattr(self, "pad_scale", SOUNDBOARD_PAD_SCALE_DEFAULT))
        for value, button in getattr(self, "scale_option_buttons", {}).items():
            button.blockSignals(True)
            button.setChecked(int(value) == current)
            button.blockSignals(False)

    def _on_pad_scale_option(self, value: int) -> None:
        self.pad_scale = max(SOUNDBOARD_PAD_SCALE_MIN, min(SOUNDBOARD_PAD_SCALE_MAX, int(value)))

        if hasattr(self, "pad_scale_slider"):
            self.pad_scale_slider.blockSignals(True)
            self.pad_scale_slider.setValue(self.pad_scale)
            self.pad_scale_slider.blockSignals(False)

        if hasattr(self, "pad_scale_value"):
            self.pad_scale_value.setText(f"{int(self.pad_scale)}%")

        self._update_scale_option_buttons()
        self._rebuild_grid()
        self.save()

    def _on_scale_panel_toggled(self, checked: bool) -> None:
        visible = bool(checked)

        for scale_widget in (
            getattr(self, "scale_label", None),
            getattr(self, "pad_scale_slider", None),
            getattr(self, "pad_scale_value", None),
        ):
            if scale_widget is not None:
                scale_widget.setVisible(False)

        options = getattr(self, "scale_options_widget", None)
        if options is not None:
            options.setVisible(visible)

        if hasattr(self, "scale_btn"):
            self.scale_btn.setText("Scale ON" if visible else "Scale")

        self._update_scale_option_buttons()


    def _on_pad_scale_preview(self, value: int) -> None:
        if hasattr(self, "pad_scale_value"):
            self.pad_scale_value.setText(f"{int(value)}%")

    def _on_pad_scale_changed(self, value: int) -> None:
        self._on_pad_scale_option(int(value))


    def _on_global_volume_changed(self, value: int) -> None:
        self.global_volume = max(0, min(100, int(value)))
        self.global_volume_value.setText(f"{int(self.global_volume)}%")
        self.save()

    def _on_auto_level_changed(self, checked: bool) -> None:
        self.auto_level_enabled = bool(checked)

        for pad in getattr(self, "pad_widgets", []):
            pad.set_auto_level_mode(self.auto_level_enabled)

        self.save()
        self.status_label.setText(
            "Auto level: ON · pad sliders = trim -24/+24 dB"
            if checked
            else "Auto level: OFF · pad sliders = volume %"
        )

    def _analyze_auto_gain(self, path: Path) -> float:
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(path),
                    "-filter:a",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            self.status_label.setText("Auto level désactivé: ffmpeg introuvable")
            return 1.0
        except Exception:
            return 1.0

        output = f"{proc.stdout}\n{proc.stderr}"
        match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
        if not match:
            return 1.0

        try:
            max_db = float(match.group(1))
        except Exception:
            return 1.0

        gain_db = SOUNDBOARD_TARGET_PEAK_DB - max_db
        gain = 10 ** (gain_db / 20.0)

        # Sécurité: on atténue les sons trop forts, mais on ne booste pas au-dessus de 100%.
        return max(0.05, min(1.0, gain))

    def _auto_gain_for_slot(self, slot: dict[str, Any], path: Path) -> float:
        if not self.auto_level_enabled:
            return 1.0

        path_text = str(path)

        try:
            cached_gain = float(slot.get("auto_gain", 1.0))
        except Exception:
            cached_gain = 1.0

        if str(slot.get("analyzed_path", "")) == path_text and 0.05 <= cached_gain <= 1.0:
            return cached_gain

        gain = self._analyze_auto_gain(path)
        slot["auto_gain"] = gain
        slot["analyzed_path"] = path_text
        self.save()

        return gain

    def _auto_level_trim_db(self, slot: dict[str, Any]) -> float:
        try:
            trim_db = float(slot.get("trim_db", SOUNDBOARD_TRIM_DB_DEFAULT))
        except Exception:
            trim_db = SOUNDBOARD_TRIM_DB_DEFAULT

        return max(SOUNDBOARD_TRIM_DB_MIN, min(SOUNDBOARD_TRIM_DB_MAX, trim_db))

    def _auto_level_cache_output(self, path: Path, trim_db: float) -> Path | None:
        try:
            stat = path.stat()
            cache_payload = {
                "path": str(path.resolve()),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "trim_db": round(float(trim_db), 2),
                "i": SOUNDBOARD_LOUDNORM_I,
                "tp": SOUNDBOARD_LOUDNORM_TP,
                "limiter": SOUNDBOARD_LIMITER_LIMIT,
                "v": 2,
            }
        except Exception:
            return None

        key = hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]

        return SOUNDBOARD_CACHE_DIR / f"{key}.wav"

    def _auto_level_audio_filter(self, trim_db: float) -> str:
        return (
            f"loudnorm=I={SOUNDBOARD_LOUDNORM_I}:"
            f"TP={SOUNDBOARD_LOUDNORM_TP}:LRA=11,"
            f"volume={float(trim_db):.2f}dB,"
            f"alimiter=limit={SOUNDBOARD_LIMITER_LIMIT}"
        )

    def _build_auto_level_cache_file(self, path: Path, output: Path, trim_db: float) -> bool:
        if output.is_file():
            return True

        try:
            SOUNDBOARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

        tmp = output.with_suffix(".tmp.wav")

        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-nostdin",
                    "-i",
                    str(path),
                    "-filter:a",
                    self._auto_level_audio_filter(trim_db),
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(tmp),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception:
            try:
                tmp.unlink()
            except Exception:
                pass
            return False

        if proc.returncode != 0 or not tmp.is_file():
            try:
                tmp.unlink()
            except Exception:
                pass
            return False

        try:
            tmp.replace(output)
        except Exception:
            return False

        return output.is_file()

    def _processed_auto_level_path(self, slot: dict[str, Any], path: Path) -> Path:
        if not self.auto_level_enabled:
            return path

        trim_db = self._auto_level_trim_db(slot)
        output = self._auto_level_cache_output(path, trim_db)
        if output is None:
            return path

        if output.is_file():
            return output

        if self._build_auto_level_cache_file(path, output, trim_db):
            return output

        return path

    def _fast_playback_path(self, slot: dict[str, Any], path: Path) -> Path:
        if not self.auto_level_enabled:
            return path

        trim_db = self._auto_level_trim_db(slot)
        output = self._auto_level_cache_output(path, trim_db)
        if output is None:
            return path

        if output.is_file():
            return output

        self._queue_auto_level_cache_build(path, output, trim_db)
        return path

    def _queue_auto_level_cache_build(self, path: Path, output: Path, trim_db: float) -> None:
        if output.is_file():
            return

        key = str(output)
        building = getattr(self, "_cache_building_keys", set())
        if key in building:
            return

        building.add(key)
        self._cache_building_keys = building

        def worker() -> None:
            try:
                self._build_auto_level_cache_file(path, output, trim_db)
            finally:
                try:
                    self._cache_building_keys.discard(key)
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            name="ksound-soundboard-cache",
            daemon=True,
        ).start()

    def _start_background_soundboard_cache(self) -> None:
        if not bool(getattr(self, "auto_level_enabled", False)):
            return

        if bool(getattr(self, "_cache_warm_thread_active", False)):
            return

        jobs: list[tuple[Path, Path, float]] = []

        for slot in list(getattr(self, "slots", [])):
            if not isinstance(slot, dict):
                continue

            path = Path(str(slot.get("path", "") or "").strip()).expanduser()
            if not path.is_file():
                continue

            trim_db = self._auto_level_trim_db(slot)
            output = self._auto_level_cache_output(path, trim_db)
            if output is not None and not output.is_file():
                jobs.append((path, output, trim_db))

        if not jobs:
            self._preload_soundboard_players()
            return

        self._cache_warm_thread_active = True

        def worker() -> None:
            try:
                for source_path, output_path, trim in jobs:
                    self._build_auto_level_cache_file(source_path, output_path, trim)
            finally:
                self._cache_warm_thread_active = False

        threading.Thread(
            target=worker,
            name="ksound-soundboard-cache-warmup",
            daemon=True,
        ).start()

    def _preload_soundboard_players(self) -> None:
        bus_found, _monitor_found = self._ensure_soundboard_output_ready("media")
        if not bus_found:
            return

        for slot in list(getattr(self, "slots", [])):
            if not isinstance(slot, dict):
                continue

            slot_id = str(slot.get("id", "") or "").strip()
            if not slot_id:
                continue

            path = Path(str(slot.get("path", "") or "").strip()).expanduser()
            if not path.is_file():
                continue

            try:
                volume = int(slot.get("volume", 80))
            except Exception:
                volume = 80

            playback_path = self._fast_playback_path(slot, path)
            effective_volume = self._effective_volume(slot, path, volume)

            self._prime_player_source(
                key=f"{slot_id}:soundboard",
                path=playback_path,
                sink_name=SOUNDBOARD_BUS,
                volume=effective_volume,
            )

    def _ensure_soundboard_output_ready(self, target_channel: str) -> tuple[bool, bool]:
        target_channel = str(target_channel or "media").strip().lower()
        if target_channel not in PLAYBACK_TARGETS:
            target_channel = "media"

        if not bool(getattr(self, "_soundboard_bus_ready", False)):
            self._soundboard_bus_ready = bool(_ensure_soundboard_bus())

        if not self._soundboard_bus_ready:
            return False, False

        routes_ready = getattr(self, "_soundboard_monitor_routes_ready", set())
        if target_channel in routes_ready:
            return True, True

        monitor_found = bool(_ensure_soundboard_monitor_route(target_channel))
        if monitor_found:
            routes_ready.add(target_channel)
            self._soundboard_monitor_routes_ready = routes_ready

        return True, monitor_found

    def _effective_volume(self, slot: dict[str, Any], path: Path, pad_volume: int) -> float:
        global_factor = max(0.0, min(1.0, float(self.global_volume) / 100.0))

        if self.auto_level_enabled:
            # En mode Auto, le +/- dB est appliqué dans le fichier cache ffmpeg.
            # Ici on garde seulement le volume global, borné à 100%.
            return max(0.0, min(100.0, 100.0 * global_factor))

        base = max(0.0, min(100.0, float(pad_volume)))
        return max(0.0, min(100.0, base * global_factor))

    def stop_all(self) -> None:
        stopped = 0
        for player, _audio in list(self._players.values()):
            try:
                player.stop()
                stopped += 1
            except Exception:
                pass
        self.status_label.setText(f"Stop all: {stopped} player(s) stopped")

    def _rebuild_shortcuts(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()

        self._shortcuts.clear()

        for slot in self.slots:
            sequence_text = str(slot.get("shortcut", "")).strip()
            if not sequence_text:
                continue

            sequence = QKeySequence(sequence_text)
            if sequence.isEmpty():
                continue

            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ApplicationShortcut)

            slot_id = str(slot.get("id", ""))
            shortcut.activated.connect(lambda sid=slot_id: self.play_slot(sid))
            self._shortcuts.append(shortcut)

    def play_slot_by_key(self, key: str) -> bool:
        wanted = _normalize_key(key)
        if not wanted:
            return False

        for index, slot in enumerate(self.slots):
            aliases = {
                _normalize_key(str(slot.get("id", ""))),
                _normalize_key(str(slot.get("label", ""))),
                _normalize_key(str(index + 1)),
                _normalize_key(f"sb{index + 1}"),
            }

            if wanted in aliases:
                self.play_slot(str(slot.get("id", _slot_id(index))))
                return True

        return False

    def _player_for_key(self, key: str, sink_name: str) -> tuple[QMediaPlayer, QAudioOutput, bool]:
        player, audio = self._players.get(key, (None, None))
        device_found = True

        if player is None or audio is None:
            player = QMediaPlayer(self)
            audio, device_found = _audio_output_for_sink_name(sink_name, self)
            player.setAudioOutput(audio)
            self._players[key] = (player, audio)

        return player, audio, device_found

    def _prime_player_source(self, *, key: str, path: Path, sink_name: str, volume: float) -> bool:
        player, audio, device_found = self._player_for_key(key, sink_name)
        audio.setVolume(max(0.0, min(1.0, float(volume) / 100.0)))

        source_path = str(path)
        if self._player_source_paths.get(key) != source_path:
            player.setSource(QUrl.fromLocalFile(source_path))
            self._player_source_paths[key] = source_path

        return device_found

    def _start_player(self, *, key: str, path: Path, sink_name: str, volume: float) -> bool:
        player, audio, device_found = self._player_for_key(key, sink_name)
        audio.setVolume(max(0.0, min(1.0, float(volume) / 100.0)))

        source_path = str(path)
        player.stop()

        if self._player_source_paths.get(key) != source_path:
            player.setSource(QUrl.fromLocalFile(source_path))
            self._player_source_paths[key] = source_path

        player.setPosition(0)
        player.play()
        return device_found

    def _schedule_output_move_fallback(self, target_channel: str) -> None:
        for delay in (90, 220, 480):
            QTimer.singleShot(delay, lambda channel=target_channel: _move_latest_soundboard_stream(channel))

    def play_slot(self, slot_id: str) -> None:
        slot = next((item for item in self.slots if str(item.get("id")) == str(slot_id)), None)
        if slot is None:
            self.status_label.setText(f"Slot not found: {slot_id}")
            return

        path = Path(str(slot.get("path", "")).strip()).expanduser()
        if not path.is_file():
            self.status_label.setText(f"No valid sound for {slot.get('label', slot_id)}")
            return

        try:
            volume = int(slot.get("volume", 80))
        except Exception:
            volume = 80

        target_channel = str(slot.get("output_channel") or "media").strip().lower()
        if target_channel not in PLAYBACK_TARGETS:
            target_channel = "media"

        playback_path = self._fast_playback_path(slot, path)
        effective_volume = self._effective_volume(slot, path, volume)

        bus_found, monitor_found = self._ensure_soundboard_output_ready(target_channel)

        output_found = False
        if bus_found:
            output_found = self._start_player(
                key=f"{slot_id}:soundboard",
                path=playback_path,
                sink_name=SOUNDBOARD_BUS,
                volume=effective_volume,
            )
            self._schedule_output_move_fallback(SOUNDBOARD_BUS)

        route_text = "SOUNDBOARD" if output_found else "SOUNDBOARD fallback"
        monitor_text = f" + Moi via {target_channel.upper()}" if monitor_found else f" + Moi route absente ({target_channel.upper()})"
        self.status_label.setText(f"Play: {slot.get('label', slot_id)} → {route_text}{monitor_text}")
