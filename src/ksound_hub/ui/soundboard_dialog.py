from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
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
PLAYBACK_TARGETS = ["media", "game", "chat", "more", "all"]
SOUNDBOARD_BUS = "soundboard"
SOUNDBOARD_MONITOR_MEDIA_NAME = "K-Sound-Hub-Soundboard-Monitor"


def _slot_id(index: int) -> str:
    return f"sb{index + 1}"


def _default_slots(count: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "id": _slot_id(index),
            "label": f"SOUND {index + 1}",
            "path": "",
            "volume": 80,
            "shortcut": "",
            "output_channel": "media",
            "send_to_micro": False,
            "trim_db": SOUNDBOARD_TRIM_DB_DEFAULT,
        }
        for index in range(count)
    ]


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

    def __init__(self, slot: dict[str, Any], parent=None):
        super().__init__(parent)
        self.slot = slot
        self.auto_level_mode = False
        self.setObjectName("soundboardPad")
        self.setMinimumWidth(230)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self.label_edit = QLineEdit(str(slot.get("label", "SOUND")))
        self.label_edit.setPlaceholderText("Nom du son")
        self.label_edit.editingFinished.connect(self._commit_label)
        top.addWidget(self.label_edit, 1)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("soundPadPlay")
        self.play_btn.setMinimumWidth(44)
        self.play_btn.clicked.connect(lambda: self.play_requested.emit(str(self.slot.get("id", ""))))
        top.addWidget(self.play_btn)

        root.addLayout(top)

        self.file_label = QLabel(self._path_label())
        self.file_label.setObjectName("mutedLabel")
        self.file_label.setWordWrap(True)
        root.addWidget(self.file_label)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(6)

        choose_btn = QPushButton("Choisir son")
        choose_btn.setObjectName("ghostButton")
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(choose_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghostButton")
        clear_btn.clicked.connect(self._clear_file)
        file_row.addWidget(clear_btn)

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

        route_label = QLabel("Moi")
        route_label.setObjectName("mutedLabel")
        route_row.addWidget(route_label)

        self.output_selector = MenuSelectorButton()
        self.output_selector.setObjectName("selectorButton")
        self.output_selector.set_items([item.upper() for item in PLAYBACK_TARGETS])
        self.output_selector.setCurrentText(str(slot.get("output_channel", "media")).upper())
        self.output_selector.currentTextChanged.connect(self._commit_output_channel)
        route_row.addWidget(self.output_selector, 1)

        self.micro_check = QCheckBox("MIC via canal")
        self.micro_check.setChecked(bool(slot.get("send_to_micro", False)))
        self.micro_check.toggled.connect(self._commit_send_to_micro)
        route_row.addWidget(self.micro_check)

        root.addLayout(route_row)

        self.shortcut_edit = QLineEdit(str(slot.get("shortcut", "")))
        self.shortcut_edit.setPlaceholderText("Shortcut app: ex. Ctrl+Alt+1")
        self.shortcut_edit.editingFinished.connect(self._commit_shortcut)
        root.addWidget(self.shortcut_edit)

    def _path_label(self) -> str:
        path = str(self.slot.get("path", "")).strip()
        if not path:
            return "Aucun fichier audio choisi"
        return Path(path).name

    def _commit_label(self) -> None:
        self.slot["label"] = self.label_edit.text().strip() or str(self.slot.get("id", "SOUND"))
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
        self.changed.emit()

    def _choose_file(self) -> None:
        current = str(self.slot.get("path", "") or "")
        start = str(Path(current).expanduser().parent) if current else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(self, "Choisir un son", start, SUPPORTED_AUDIO_FILTER)
        if not filename:
            return

        self.slot["path"] = filename

        current_label = self.label_edit.text().strip()
        if not current_label or current_label.startswith("SOUND "):
            auto_label = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
            if auto_label:
                self.slot["label"] = auto_label
                self.label_edit.setText(auto_label)

        self.file_label.setText(self._path_label())
        self.changed.emit()

    def _clear_file(self) -> None:
        self.slot["path"] = ""
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
        self.pad_widgets: list[SoundboardPadWidget] = []
        self._players: dict[str, tuple[QMediaPlayer, QAudioOutput]] = {}
        self._shortcuts: list[QShortcut] = []

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
            "Pads audio avec volume indépendant. Le son sort toujours dans le canal SOUNDBOARD. "
            "'Moi' choisit où tu l’entends. Pour le micro: MICRO → Apps → + → SOUNDBOARD."
        )
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        root.addWidget(header)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedLabel")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setObjectName("scrollViewport")

        host = QWidget()
        host.setObjectName("columnsHost")

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

        global_label = QLabel("Global")
        global_label.setObjectName("mutedLabel")
        footer_layout.addWidget(global_label)

        self.global_volume_slider = SoundboardNoWheelSlider(Qt.Horizontal)
        self.global_volume_slider.setRange(0, 100)
        self.global_volume_slider.setFixedWidth(130)
        self.global_volume_slider.setValue(int(self.global_volume))
        self.global_volume_slider.valueChanged.connect(self._on_global_volume_changed)
        footer_layout.addWidget(self.global_volume_slider)

        self.global_volume_value = QLabel(f"{int(self.global_volume)}%")
        self.global_volume_value.setObjectName("mutedLabel")
        self.global_volume_value.setMinimumWidth(38)
        footer_layout.addWidget(self.global_volume_value)

        add_btn = QPushButton("+ 4 pads")
        add_btn.setObjectName("ghostButton")
        add_btn.clicked.connect(self.add_four_slots)
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
            QPushButton#soundPadPlay {
                font-size: 18px;
                font-weight: 900;
                border-radius: 13px;
                padding: 6px 10px;
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
            QCheckBox {
                background: transparent;
                font-size: 11px;
            }
            """
        )

        self._rebuild_grid()
        self._rebuild_shortcuts()

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

        return [_clean_slot(item if isinstance(item, dict) else {}, index) for index, item in enumerate(raw_slots)]

    def save(self) -> None:
        SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOUNDBOARD_PATH.write_text(
            json.dumps(
                {
                    "global_volume": int(getattr(self, "global_volume", SOUNDBOARD_GLOBAL_VOLUME_DEFAULT)),
                    "auto_level_enabled": bool(getattr(self, "auto_level_enabled", SOUNDBOARD_AUTO_LEVEL_DEFAULT)),
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

    def add_four_slots(self) -> None:
        start = len(self.slots)
        self.slots.extend(_default_slots(4 + start)[start:])
        self._rebuild_grid()
        self.save()

    def _rebuild_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.pad_widgets.clear()

        columns = 4
        for index, slot in enumerate(self.slots):
            pad = SoundboardPadWidget(slot, self)
            pad.set_auto_level_mode(self.auto_level_enabled)
            pad.changed.connect(self.save)
            pad.play_requested.connect(self.play_slot)
            self.pad_widgets.append(pad)
            self.grid.addWidget(pad, index // columns, index % columns)

        self.grid.setRowStretch((len(self.slots) + columns - 1) // columns, 1)

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

    def _processed_auto_level_path(self, slot: dict[str, Any], path: Path) -> Path:
        if not self.auto_level_enabled:
            return path

        try:
            trim_db = float(slot.get("trim_db", SOUNDBOARD_TRIM_DB_DEFAULT))
        except Exception:
            trim_db = SOUNDBOARD_TRIM_DB_DEFAULT

        trim_db = max(SOUNDBOARD_TRIM_DB_MIN, min(SOUNDBOARD_TRIM_DB_MAX, trim_db))

        try:
            stat = path.stat()
            cache_payload = {
                "path": str(path.resolve()),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "trim_db": round(trim_db, 2),
                "i": SOUNDBOARD_LOUDNORM_I,
                "tp": SOUNDBOARD_LOUDNORM_TP,
                "limiter": SOUNDBOARD_LIMITER_LIMIT,
                "v": 2,
            }
        except Exception:
            return path

        key = hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]

        SOUNDBOARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        output = SOUNDBOARD_CACHE_DIR / f"{key}.wav"

        if output.is_file():
            return output

        tmp = output.with_suffix(".tmp.wav")

        # Important:
        # - loudnorm rapproche les fichiers entre eux.
        # - volume=trim_db applique le +/- dB réel.
        # - alimiter empêche le clipping au lieu de laisser saturer.
        audio_filter = (
            f"loudnorm=I={SOUNDBOARD_LOUDNORM_I}:"
            f"TP={SOUNDBOARD_LOUDNORM_TP}:LRA=11,"
            f"volume={trim_db}dB,"
            f"alimiter=limit={SOUNDBOARD_LIMITER_LIMIT}"
        )

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
                    audio_filter,
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
        except FileNotFoundError:
            self.status_label.setText("Auto level cache: ffmpeg introuvable")
            return path
        except Exception as exc:
            self.status_label.setText(f"Auto level cache erreur: {exc}")
            return path

        if proc.returncode != 0 or not tmp.is_file():
            self.status_label.setText("Auto level cache: ffmpeg failed")
            try:
                tmp.unlink()
            except Exception:
                pass
            return path

        try:
            tmp.replace(output)
        except Exception:
            return path

        return output

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

    def _start_player(self, *, key: str, path: Path, sink_name: str, volume: float) -> bool:
        player, audio, device_found = self._player_for_key(key, sink_name)
        audio.setVolume(max(0.0, min(1.0, float(volume) / 100.0)))
        player.stop()
        player.setSource(QUrl.fromLocalFile(str(path)))
        player.setPosition(0)
        player.play()
        return device_found

    def _schedule_output_move_fallback(self, target_channel: str) -> None:
        for delay in (90, 220, 480):
            QTimer.singleShot(delay, lambda channel=target_channel: _move_latest_soundboard_stream(channel))

    def play_slot(self, slot_id: str) -> None:
        slot = next((item for item in self.slots if str(item.get("id")) == str(slot_id)), None)
        if slot is None:
            self.status_label.setText(f"Slot introuvable: {slot_id}")
            return

        path = Path(str(slot.get("path", "")).strip()).expanduser()
        if not path.is_file():
            self.status_label.setText(f"Aucun son valide pour {slot.get('label', slot_id)}")
            return

        volume = int(slot.get("volume", 80))
        target_channel = str(slot.get("output_channel") or "media").strip().lower()
        if target_channel not in PLAYBACK_TARGETS:
            target_channel = "media"

        playback_path = self._processed_auto_level_path(slot, path)
        effective_volume = self._effective_volume(slot, path, volume)

        bus_found = _ensure_soundboard_bus()
        monitor_found = _ensure_soundboard_monitor_route(target_channel) if bus_found else False

        # Source unique:
        # - le son naît dans le sink SOUNDBOARD
        # - soundboard.monitor est recopié vers le canal "Moi"
        # - MICRO peut prendre SOUNDBOARD séparément via MICRO → Apps → + → SOUNDBOARD
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
