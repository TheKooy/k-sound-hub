from __future__ import annotations

import copy
import os
import subprocess

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QFrame,
    QWidget,
)

from ..audio.engine import AudioEngine
from ..models import ChannelConfig, EqProfile
from .eq_dialog import EqProfileDialog
from .widgets import ChannelVolumeSlider, MenuSelectorButton, CollapsibleSection, HeaderBadge, SelectorFrame, StereoLevelMeterWidget

CHANNEL_META = {
    "all": {"icon": "🌍", "apps": []},
    "game": {"icon": "🎮", "apps": []},
    "chat": {"icon": "💬", "apps": []},
    "media": {"icon": "🎵", "apps": []},
    "more": {"icon": "🔊", "apps": []},
    "micro": {"icon": "🎤", "apps": []},
    "return-mic": {"icon": "🎧", "apps": []},
}

SYSTEM_DEFAULT_CHOICE = "System default"
PLAYBACK_CHANNEL_KEYS = {"all", "game", "chat", "media", "more"}
MIC_LINKABLE_CHANNEL_KEYS = ["all", "game", "chat", "media", "more", "soundboard"]
INTERNAL_SINK_NAMES = {"all", "game", "chat", "media", "more", "retour", "micro_bus", "soundboard"}
INTERNAL_SOURCE_NAMES = {"micro"}
RETURN_MIC_MONITOR_SOURCE_PREFIX = "source:"
RETURN_MIC_MONITOR_STATIC_CHOICES: list[tuple[str, str]] = [
    ("soundboard", "SOUNDBOARD"),
    ("micro-final", "MIC final"),
]

SOUNDBOARD_MIC_MEDIA_NAME = "K-Sound-Hub-Soundboard-To-Micro"


def _native_micro_enabled_channel_widget() -> bool:
    return str(os.environ.get("KSH_NATIVE_MIC", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _run_pactl_channel_widget(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=2.0)


def _list_short_audio_names_channel_widget(kind: str) -> list[str]:
    proc = _run_pactl_channel_widget(["list", "short", kind])
    if proc.returncode != 0:
        return []

    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1])
    return names


def _default_audio_name_channel_widget(kind: str) -> str:
    query = "get-default-sink" if kind == "sinks" else "get-default-source"
    proc = _run_pactl_channel_widget([query])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _pactl_descriptions_by_name_channel_widget(kind: str) -> dict[str, str]:
    proc = _run_pactl_channel_widget(["list", kind])
    if proc.returncode != 0:
        return {}

    descriptions: dict[str, str] = {}
    current_name = ""
    current_description = ""

    def flush() -> None:
        nonlocal current_name, current_description
        if current_name:
            descriptions[current_name] = current_description or current_name
        current_name = ""
        current_description = ""

    for raw_line in proc.stdout.splitlines():
        stripped = raw_line.strip()

        if stripped.startswith("Sink #") or stripped.startswith("Source #"):
            flush()
            continue

        if stripped.startswith("Name:"):
            current_name = stripped.split(":", 1)[1].strip()
            continue

        if stripped.startswith("Description:"):
            current_description = stripped.split(":", 1)[1].strip()
            continue

        if not current_description and (
            stripped.startswith("device.description =")
            or stripped.startswith("node.description =")
            or stripped.startswith("device.product.name =")
            or stripped.startswith("device.nick =")
        ):
            value = stripped.split("=", 1)[1].strip().strip('"')
            if value:
                current_description = value

    flush()
    return descriptions


def _clean_audio_label_channel_widget(label: str) -> str:
    text = str(label).strip()
    if not text:
        return ""

    text = text.replace("Monitor of ", "")
    text = text.replace(" Analog Stereo", "")
    text = text.replace(" Digital Stereo", "")
    text = text.replace(" Mono", "")
    text = text.replace(" (IEC958)", "")
    text = text.replace("Front Headphones", "Headphones")
    text = text.replace("S/PDIF Output", "S/PDIF")
    text = text.replace("Speakers Output", "Speakers")
    return " ".join(text.split())


def _short_node_suffix_channel_widget(name: str) -> str:
    tail = name.rsplit(".", 1)[-1] if "." in name else name
    tail = tail.replace("_", " ").replace("-", " ").strip()
    return tail or name[-28:]


def _audio_choice_maps_channel_widget(
    *,
    kind: str,
    raw_choices: list[str],
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    descriptions = _pactl_descriptions_by_name_channel_widget(kind)
    default = _default_audio_name_channel_widget(kind)

    if not raw_choices:
        return [SYSTEM_DEFAULT_CHOICE], {SYSTEM_DEFAULT_CHOICE: ""}, {"": SYSTEM_DEFAULT_CHOICE}

    labels: list[str] = []
    label_to_name: dict[str, str] = {}
    name_to_label: dict[str, str] = {}

    for name in raw_choices:
        base_label = _clean_audio_label_channel_widget(descriptions.get(name, name)) or name

        if name == default:
            base_label = f"{base_label} · default"

        label = base_label
        if label in label_to_name and label_to_name[label] != name:
            label = f"{base_label} ({_short_node_suffix_channel_widget(name)})"

        counter = 2
        unique_label = label
        while unique_label in label_to_name and label_to_name[unique_label] != name:
            unique_label = f"{label} #{counter}"
            counter += 1

        labels.append(unique_label)
        label_to_name[unique_label] = name
        name_to_label[name] = unique_label

    return labels, label_to_name, name_to_label


def _playback_target_choices_channel_widget() -> list[str]:
    names = _list_short_audio_names_channel_widget("sinks")
    default = _default_audio_name_channel_widget("sinks")
    choices = [name for name in names if name not in INTERNAL_SINK_NAMES]

    if default and default not in INTERNAL_SINK_NAMES and default in names:
        choices = [default] + [name for name in choices if name != default]

    return choices or ([default] if default else []) or []


def _micro_input_choices_channel_widget() -> list[str]:
    names = _list_short_audio_names_channel_widget("sources")
    default = _default_audio_name_channel_widget("sources")
    choices = [
        name for name in names
        if name not in INTERNAL_SOURCE_NAMES
        and ".monitor" not in name
        and not name.endswith(".monitor")
    ]

    if default and default not in INTERNAL_SOURCE_NAMES and ".monitor" not in default and default in names:
        choices = [default] + [name for name in choices if name != default]

    return choices or ([default] if default else []) or []


def _return_monitor_choices_channel_widget() -> list[tuple[str, str]]:
    choices = list(RETURN_MIC_MONITOR_STATIC_CHOICES)
    raw_sources = _micro_input_choices_channel_widget()
    _labels, _label_to_source, source_to_label = _audio_choice_maps_channel_widget(
        kind="sources",
        raw_choices=raw_sources,
    )

    for source_name in raw_sources:
        label = source_to_label.get(source_name, source_name)
        choices.append((f"{RETURN_MIC_MONITOR_SOURCE_PREFIX}{source_name}", label))

    return choices


def _return_monitor_label_for_key_channel_widget(key: str) -> str:
    raw_key = str(key)
    key_lower = raw_key.lower()

    for choice_key, label in _return_monitor_choices_channel_widget():
        if choice_key.lower() == key_lower:
            return label

    if key_lower.startswith(RETURN_MIC_MONITOR_SOURCE_PREFIX):
        source_name = raw_key.split(":", 1)[1]
        _labels, _label_to_source, source_to_label = _audio_choice_maps_channel_widget(
            kind="sources",
            raw_choices=[source_name],
        )
        return source_to_label.get(source_name, source_name)

    return ""


def _return_monitor_key_for_label_channel_widget(label: str) -> str:
    for key, choice_label in _return_monitor_choices_channel_widget():
        if choice_label == label:
            return key
    return ""



def _sink_exists_channel_widget(name: str) -> bool:
    proc = _run_pactl_channel_widget(["list", "short", "sinks"])
    if proc.returncode != 0:
        return False
    return any(line.split()[1] == name for line in proc.stdout.splitlines() if len(line.split()) >= 2)


def _ensure_soundboard_sink_channel_widget() -> bool:
    if _sink_exists_channel_widget("soundboard"):
        return True

    proc = _run_pactl_channel_widget([
        "load-module",
        "module-null-sink",
        "sink_name=soundboard",
        "sink_properties=device.description=🎛SOUNDBOARD media.name=K-Sound-Hub-Soundboard-Bus",
        "channels=2",
        "rate=48000",
    ])
    return proc.returncode == 0 or _sink_exists_channel_widget("soundboard")


def _soundboard_micro_module_ids_channel_widget() -> list[str]:
    proc = _run_pactl_channel_widget(["list", "modules", "short"])
    if proc.returncode != 0:
        return []

    ids: list[str] = []
    for line in proc.stdout.splitlines():
        if "source=soundboard.monitor" not in line:
            continue
        if "sink=micro_bus" not in line:
            continue
        if SOUNDBOARD_MIC_MEDIA_NAME not in line:
            continue

        parts = line.split(None, 1)
        if parts:
            ids.append(parts[0])

    return ids


def _set_soundboard_to_micro_channel_widget(enabled: bool) -> bool:
    existing = _soundboard_micro_module_ids_channel_widget()

    if _native_micro_enabled_channel_widget():
        # Native micro engine reads soundboard.monitor directly.
        # Keep the soundboard sink available, but do not create the old loopback.
        ok = True
        for module_id in existing:
            proc = _run_pactl_channel_widget(["unload-module", module_id])
            ok = ok and proc.returncode == 0

        if enabled:
            ok = _ensure_soundboard_sink_channel_widget() and ok

        return ok

    if enabled:
        if existing:
            return True

        if not _ensure_soundboard_sink_channel_widget():
            return False

        if not _sink_exists_channel_widget("micro_bus"):
            return False

        proc = _run_pactl_channel_widget([
            "load-module",
            "module-loopback",
            "source=soundboard.monitor",
            "sink=micro_bus",
            "latency_msec=20",
            "source_dont_move=true",
            "sink_dont_move=true",
            f"sink_input_properties=media.name={SOUNDBOARD_MIC_MEDIA_NAME}",
        ])
        return proc.returncode == 0

    ok = True
    for module_id in existing:
        proc = _run_pactl_channel_widget(["unload-module", module_id])
        ok = ok and proc.returncode == 0

    return ok


def _sync_soundboard_to_micro_from_links_channel_widget(linked_channels: list[str]) -> None:
    try:
        enabled = "soundboard" in [str(key).lower() for key in linked_channels]
        _set_soundboard_to_micro_channel_widget(enabled)
    except Exception:
        pass



class NoWheelAppListWidget(QListWidget):
    """App list where mouse wheel scrolling is disabled.

    The wheel event is ignored, not accepted, so the parent scroll area can
    still scroll when the cursor is above the apps section.
    """

    def wheelEvent(self, event) -> None:
        event.ignore()


class ClickOutsideMessageDialog(QDialog):
    def __init__(self, title: str, text: str, *, icon=QMessageBox.Information, parent=None):
        super().__init__(parent)
        self._app = QApplication.instance()
        self._owner_window = parent.window() if parent is not None else None
        self._filter_installed = False

        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)

        icon_label = QLabel()
        if icon == QMessageBox.Warning:
            pix = self.style().standardIcon(QStyle.SP_MessageBoxWarning).pixmap(40, 40)
        else:
            pix = self.style().standardIcon(QStyle.SP_MessageBoxInformation).pixmap(40, 40)
        icon_label.setPixmap(pix)
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        body.addWidget(icon_label, 0)

        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.NoTextInteraction)
        body.addWidget(text_label, 1)

        root.addLayout(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.adjustSize()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._app is not None and not self._filter_installed:
            self._app.installEventFilter(self)
            self._filter_installed = True

    def hideEvent(self, event) -> None:
        self._remove_event_filter()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._remove_event_filter()
        super().closeEvent(event)

    def _remove_event_filter(self) -> None:
        if self._app is not None and self._filter_installed:
            try:
                self._app.removeEventFilter(self)
            except Exception:
                pass
            self._filter_installed = False

    def eventFilter(self, obj, event) -> bool:
        if not self.isVisible():
            return super().eventFilter(obj, event)

        if event.type() != QEvent.MouseButtonPress:
            return super().eventFilter(obj, event)

        if not isinstance(obj, QWidget):
            return super().eventFilter(obj, event)

        if obj is self or self.isAncestorOf(obj):
            return super().eventFilter(obj, event)

        if self._owner_window is not None and obj.window() is self._owner_window:
            self.close()
            return False

        return super().eventFilter(obj, event)


class ChannelWidget(QFrame):
    changed = Signal()

    def __init__(
        self,
        channel: ChannelConfig,
        global_visualizer_enabled: bool,
        audio_engine: AudioEngine | None = None,
        on_runtime_refresh=None,
        parent=None,
    ):
        super().__init__(parent)
        self.channel = channel
        self.global_visualizer_enabled = global_visualizer_enabled
        self.audio_engine = audio_engine
        self.on_runtime_refresh = on_runtime_refresh
        self._change_hint = "init"
        self._slider_drag_active = False

        self.setObjectName("channelCard")
        self._card_width = 152
        self.setFixedWidth(self._card_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(7)

        meta = CHANNEL_META.get(channel.key, {"icon": "🎚", "apps": ["No routed apps yet"]})

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)

        icon_label = QLabel(meta["icon"])
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 20px; background: transparent;")
        header.addWidget(icon_label)

        title = QLabel(channel.name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 900; background: transparent;")
        header.addWidget(title)

        root.addLayout(header)

        self.device_combo: MenuSelectorButton | None = None
        self.return_mode_combo: MenuSelectorButton | None = None
        self.eq_list: QListWidget | None = None
        self.apps_list: QListWidget | None = None
        self._selector_frames: list[tuple[QFrame, int]] = []

        controls_row = self._build_primary_controls()
        if controls_row is not None:
            root.addWidget(controls_row, 0, Qt.AlignHCenter)

        self.volume_percent = QLabel(f"{self.channel.volume}%")
        self.volume_percent.setAlignment(Qt.AlignCenter)
        self.volume_percent.setStyleSheet("font-size: 12px; font-weight: 800; background: transparent;")
        root.addWidget(self.volume_percent)

        self.left_meter = StereoLevelMeterWidget("L")
        self.right_meter = StereoLevelMeterWidget("R")
        meter_height = 162
        self.left_meter.setFixedHeight(meter_height)
        self.right_meter.setFixedHeight(meter_height)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(4)
        slider_row.addStretch(1)
        slider_row.addWidget(self.left_meter, 0, Qt.AlignBottom)

        self.slider = ChannelVolumeSlider()
        self.slider.setObjectName("channelVolumeSlider")
        self.slider.setRange(0, 100)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setTracking(True)
        self.slider.setValue(channel.volume)
        self.slider.valueChanged.connect(self._on_volume_changed)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.setFixedHeight(meter_height)
        self.slider.setFixedWidth(32)

        slider_host = QWidget()
        slider_host.setAttribute(Qt.WA_TranslucentBackground, True)
        slider_host.setAutoFillBackground(False)
        slider_host.setStyleSheet("background: transparent;")
        slider_host_layout = QVBoxLayout(slider_host)
        slider_host_layout.setContentsMargins(0, 0, 0, 0)
        slider_host_layout.setSpacing(0)
        slider_host_layout.addWidget(self.slider, 0, Qt.AlignHCenter)

        slider_row.addWidget(slider_host, 0, Qt.AlignHCenter)
        slider_row.addWidget(self.right_meter, 0, Qt.AlignBottom)
        slider_row.addStretch(1)
        root.addLayout(slider_row)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.down_btn = QPushButton("−")
        self.down_btn.setObjectName("tinyButton")
        self.down_btn.clicked.connect(lambda: self.slider.setValue(max(0, self.slider.value() - 5)))
        controls.addWidget(self.down_btn)

        self.mute_btn = QPushButton("Mute")
        self.mute_btn.setObjectName("muteButton")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setChecked(channel.muted)
        self.mute_btn.toggled.connect(self._on_muted_changed)
        controls.addWidget(self.mute_btn, 1)

        self.up_btn = QPushButton("+")
        self.up_btn.setObjectName("tinyButton")
        self.up_btn.clicked.connect(lambda: self.slider.setValue(min(100, self.slider.value() + 5)))
        controls.addWidget(self.up_btn)
        root.addLayout(controls)

        self.apps_section = CollapsibleSection("Apps")
        self._populate_apps_section(meta["apps"])
        root.addWidget(self.apps_section)

        self.eq_section = CollapsibleSection("EQ")
        self._populate_eq_section()
        root.addWidget(self.eq_section)

        self.details_section = CollapsibleSection("Info / Options")
        self._populate_details_section()
        root.addWidget(self.details_section)

        root.addStretch(1)
        self._set_meter_visibility()

    def _emit_changed(self, hint: str) -> None:
        self._change_hint = hint
        self.changed.emit()

    def set_meter_levels(self, left: float, right: float) -> None:
        if not (self.global_visualizer_enabled and self.channel.visualizer_enabled):
            self.left_meter.clear()
            self.right_meter.clear()
            return
        self.left_meter.set_level(left)
        self.right_meter.set_level(right)

    def clear_meter_levels(self) -> None:
        self.left_meter.clear()
        self.right_meter.clear()

    def _default_primary_target(self) -> str:
        if self.channel.key == "micro":
            choices = _micro_input_choices_channel_widget()
            return choices[0] if choices else ""

        choices = _playback_target_choices_channel_widget()
        return choices[0] if choices else ""



    def _selector_frame(self, combo: MenuSelectorButton, frame_width: int = 130) -> QFrame:
        # Use the project's styled SelectorFrame instead of a transparent raw QFrame.
        # This restores the visible rounded border/background around device selectors.
        frame = SelectorFrame()
        frame.setObjectName("selectorFrame")
        frame.setFixedWidth(frame_width)
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._selector_frames.append((frame, frame_width))

        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(0)

        combo.setObjectName("selectorButton")
        combo.setMinimumHeight(26)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(combo, 1)

        return frame

    def _build_primary_controls(self) -> QWidget | None:
        if self.channel.key == "micro":
            raw_choices = _micro_input_choices_channel_widget()
            labels, label_to_target, target_to_label = _audio_choice_maps_channel_widget(
                kind="sources",
                raw_choices=raw_choices,
            )
            frame_width = 220
        else:
            raw_choices = _playback_target_choices_channel_widget()
            labels, label_to_target, target_to_label = _audio_choice_maps_channel_widget(
                kind="sinks",
                raw_choices=raw_choices,
            )
            frame_width = 220

        self._device_label_to_target = label_to_target
        self._device_target_to_label = target_to_label

        if raw_choices and (not self.channel.primary_target or self.channel.primary_target not in raw_choices):
            self.channel.primary_target = raw_choices[0]
        elif not raw_choices:
            self.channel.primary_target = ""

        box = QWidget()
        box.setAttribute(Qt.WA_TranslucentBackground, True)
        box.setAutoFillBackground(False)
        box.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)

        self.device_combo = MenuSelectorButton()
        self.device_combo.set_items(labels or [SYSTEM_DEFAULT_CHOICE])
        self._prepare_selector(self.device_combo)
        self._set_selector_text(self.device_combo, self.channel.primary_target or SYSTEM_DEFAULT_CHOICE)
        self.device_combo.setToolTip(self.channel.primary_target or SYSTEM_DEFAULT_CHOICE)
        self.device_combo.currentTextChanged.connect(self._on_primary_target_changed)
        outer.addWidget(self._selector_frame(self.device_combo, frame_width=frame_width), 0, Qt.AlignCenter)

        outer.addStretch(1)
        return box


    def _set_selector_text(self, combo: MenuSelectorButton, value: str) -> None:
        target_to_label = getattr(self, "_device_target_to_label", {})
        display_value = target_to_label.get(value, value)
        combo.setCurrentText(display_value)

    def _prepare_selector(self, combo: MenuSelectorButton) -> None:
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_card_width(self, width: int) -> None:
        if self.channel.key == "micro":
            self._card_width = max(166, min(186, int(width) + 12))
        else:
            self._card_width = max(136, min(156, int(width)))
        self.setFixedWidth(self._card_width)
        self._resize_selector_frames()

    def _resize_selector_frames(self) -> None:
        if not self._selector_frames:
            return

        available = max(104, self._card_width - 22)
        for frame, base_width in self._selector_frames:
            frame.setFixedWidth(min(base_width, available))

    def _set_meter_visibility(self) -> None:
        visible = self.global_visualizer_enabled and self.channel.visualizer_enabled
        self.left_meter.setVisible(visible)
        self.right_meter.setVisible(visible)
        if not visible:
            self.left_meter.clear()
            self.right_meter.clear()

    def _populate_apps_section(self, app_names: list[str]) -> None:
        badge_row = QHBoxLayout()
        badge_row.addWidget(HeaderBadge("Sources" if self.channel.key == "return-mic" else "Active"))
        badge_row.addStretch(1)
        self.apps_section.content_layout.addLayout(badge_row)

        self.apps_list = NoWheelAppListWidget()
        self.apps_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.apps_list.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.apps_list.setMinimumHeight(96)
        self.apps_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.apps_section.content_layout.addWidget(self.apps_list)

        actions = QHBoxLayout()
        add_btn = QPushButton("+")
        add_btn.setObjectName("tinyButton")
        add_btn.clicked.connect(self._add_app_route)

        remove_btn = QPushButton("🗑")
        remove_btn.setObjectName("tinyButton")
        remove_btn.clicked.connect(self._remove_selected_app_route)

        actions.addWidget(add_btn)
        actions.addStretch(1)
        actions.addWidget(remove_btn)
        self.apps_section.content_layout.addLayout(actions)

        self._reload_app_routes(fallback_names=app_names)

    def _reload_app_routes(self, fallback_names: list[str] | None = None) -> None:
        if self.apps_list is None:
            return

        self.apps_list.clear()

        if self.channel.key == "return-mic":
            shown = 0
            for key in self.channel.linked_channels:
                key_text = str(key)
                label = _return_monitor_label_for_key_channel_widget(key_text)
                if not label:
                    continue
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, key_text)
                self.apps_list.addItem(item)
                shown += 1

            if shown == 0:
                item = QListWidgetItem("No monitored source")
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.apps_list.addItem(item)
            return

        if self.channel.key == "micro":
            _sync_soundboard_to_micro_from_links_channel_widget(self.channel.linked_channels)
            shown = 0
            for key in self.channel.linked_channels:
                if key not in MIC_LINKABLE_CHANNEL_KEYS:
                    continue
                item = QListWidgetItem(key.upper())
                item.setData(Qt.UserRole, key)
                self.apps_list.addItem(item)
                shown += 1

            if shown == 0 and fallback_names:
                for app_name in fallback_names[:1]:
                    item = QListWidgetItem(app_name)
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    self.apps_list.addItem(item)
            return

        if self.audio_engine is None or self.channel.key not in PLAYBACK_CHANNEL_KEYS:
            for app_name in (fallback_names or []):
                self.apps_list.addItem(QListWidgetItem(app_name))
            return

        streams = self.audio_engine.list_sink_inputs()
        shown = 0
        for stream in streams:
            if stream.sink_name != self.channel.key:
                continue
            item = QListWidgetItem(stream.display_name)
            item.setData(Qt.UserRole, stream.stream_id)
            item.setData(Qt.UserRole + 1, stream.app_name)
            item.setData(Qt.UserRole + 2, stream.binary_name)
            self.apps_list.addItem(item)
            shown += 1

        if shown == 0 and fallback_names:
            for app_name in fallback_names[:1]:
                item = QListWidgetItem(app_name)
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.apps_list.addItem(item)

    def _add_app_route(self) -> None:
        if self.channel.key == "return-mic":
            current = {str(key).lower() for key in self.channel.linked_channels}
            available = [label for key, label in _return_monitor_choices_channel_widget() if key.lower() not in current]
            if not available:
                self._show_click_outside_message("Mic Output Monitor", "All monitorable sources are already added.")
                return

            choice, ok = QInputDialog.getItem(
                self,
                "Add to MIC OUT",
                "Source to monitor",
                available,
                0,
                False,
            )
            if not ok or not choice:
                return

            key = _return_monitor_key_for_label_channel_widget(choice)
            if not key:
                return


            if key not in [str(existing).lower() for existing in self.channel.linked_channels]:
                self.channel.linked_channels.append(key)

            self._emit_changed("return_micro_sources")
            return

        if self.channel.key == "micro":
            available = [key.upper() for key in MIC_LINKABLE_CHANNEL_KEYS if key not in self.channel.linked_channels]
            if not available:
                self._show_click_outside_message("Micro sends", "All playback channels and SOUNDBOARD are already sent to MICRO.")
                return

            choice, ok = QInputDialog.getItem(
                self,
                "Send channel to MICRO",
                "Playback channels / soundboard",
                available,
                0,
                False,
            )
            if not ok or not choice:
                return

            key = choice.lower()
            if key not in self.channel.linked_channels:
                self.channel.linked_channels.append(key)
                if key == "soundboard":
                    if not _set_soundboard_to_micro_channel_widget(True):
                        self._show_click_outside_message(
                            "Micro sends",
                            "SOUNDBOARD was added, but the soundboard.monitor → micro_bus link could not be created.",
                            icon=QMessageBox.Warning,
                        )
                self._emit_changed("micro_links")
            return

        if self.audio_engine is None or self.channel.key not in PLAYBACK_CHANNEL_KEYS:
            return

        streams = [s for s in self.audio_engine.list_sink_inputs() if s.sink_name != self.channel.key]
        if not streams:
            self._show_click_outside_message("Apps", "No active audio app available to move.")
            return

        choices = []
        mapping: dict[str, int] = {}
        for stream in streams:
            label = f"{stream.display_name} [{stream.stream_id}]"
            if stream.sink_name:
                label += f" → {stream.sink_name}"
            choices.append(label)
            mapping[label] = stream.stream_id

        choice, ok = QInputDialog.getItem(
            self,
            f"Send app to {self.channel.name}",
            "Active apps",
            choices,
            0,
            False,
        )
        if not ok or not choice:
            return

        stream_id = mapping[choice]
        chosen_stream = next((s for s in streams if s.stream_id == stream_id), None)

        if not self.audio_engine.move_sink_input_to_channel(stream_id, self.channel.key):
            self._show_click_outside_message(
                "Apps",
                "Unable to move this app to the selected channel.",
                icon=QMessageBox.Warning,
            )
            return

        rule = ""
        if chosen_stream is not None:
            if chosen_stream.media_name and chosen_stream.display_name.startswith("SOUNDBOARD"):
                rule = f"media:{chosen_stream.media_name}"
            elif chosen_stream.node_name and chosen_stream.display_name.startswith("SOUNDBOARD"):
                rule = f"node:{chosen_stream.node_name}"
            elif chosen_stream.binary_name:
                rule = f"bin:{chosen_stream.binary_name}"
            elif chosen_stream.app_name:
                rule = f"app:{chosen_stream.app_name}"

        if rule and rule not in self.channel.app_rules:
            self.channel.app_rules.append(rule)

        self._emit_changed("app_route")

        if callable(self.on_runtime_refresh):
            self.on_runtime_refresh()

    def _remove_selected_app_route(self) -> None:
        item = self.apps_list.currentItem() if self.apps_list is not None else None
        if item is None:
            return

        if self.channel.key == "return-mic":
            linked_key = item.data(Qt.UserRole)
            if not isinstance(linked_key, str):
                return
            self.channel.linked_channels = [
                key for key in self.channel.linked_channels
                if str(key).lower() != linked_key.lower()
            ]
            self._emit_changed("return_micro_sources")
            return

        if self.channel.key == "micro":
            linked_key = item.data(Qt.UserRole)
            if not isinstance(linked_key, str):
                return
            self.channel.linked_channels = [key for key in self.channel.linked_channels if key != linked_key]
            if linked_key == "soundboard":
                _set_soundboard_to_micro_channel_widget(False)
            self._emit_changed("micro_links")
            return

        if self.audio_engine is None or self.channel.key not in PLAYBACK_CHANNEL_KEYS:
            return

        stream_id = item.data(Qt.UserRole)
        if not isinstance(stream_id, int):
            return

        if self.channel.key == "all":
            self._show_click_outside_message("Apps", "This app is already on ALL.")
            return

        app_name = item.data(Qt.UserRole + 1)
        binary_name = item.data(Qt.UserRole + 2)

        if not self.audio_engine.move_sink_input_to_channel(stream_id, "all"):
            self._show_click_outside_message(
                "Apps",
                "Unable to move this app back to ALL.",
                icon=QMessageBox.Warning,
            )
            return

        for rule in (
            f"bin:{binary_name}" if isinstance(binary_name, str) and binary_name else "",
            f"app:{app_name}" if isinstance(app_name, str) and app_name else "",
        ):
            if rule:
                self.channel.app_rules = [x for x in self.channel.app_rules if x != rule]

        self._emit_changed("app_route")

        if callable(self.on_runtime_refresh):
            self.on_runtime_refresh()

    def refresh_runtime_views(self) -> None:
        meta = CHANNEL_META.get(self.channel.key, {"apps": []})
        self._reload_app_routes(fallback_names=meta["apps"])
        self._reload_profiles()

    def _show_click_outside_message(
        self,
        title: str,
        text: str,
        *,
        icon=QMessageBox.Information,
    ) -> None:
        box = ClickOutsideMessageDialog(title, text, icon=icon, parent=self)
        box.show()
        box.raise_()
        box.activateWindow()

    def _populate_eq_section(self) -> None:
        badge_row = QHBoxLayout()
        badge_row.addWidget(HeaderBadge("Presets"))
        badge_row.addStretch(1)
        self.eq_section.content_layout.addLayout(badge_row)

        self.eq_list = QListWidget()
        self.eq_list.setMinimumHeight(82)
        self.eq_list.setStyleSheet("font-size: 11px;")
        self.eq_list.currentItemChanged.connect(self._on_eq_selection_changed)
        self.eq_section.content_layout.addWidget(self.eq_list)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)

        add_profile_btn = QPushButton("+")
        add_profile_btn.setObjectName("tinyButton")
        add_profile_btn.clicked.connect(self._add_profile)
        actions.addWidget(add_profile_btn)

        actions.addStretch(1)

        edit_profile_btn = QPushButton("✎")
        edit_profile_btn.setObjectName("tinyButton")
        edit_profile_btn.clicked.connect(self._edit_profile)
        actions.addWidget(edit_profile_btn)

        remove_profile_btn = QPushButton("🗑")
        remove_profile_btn.setObjectName("tinyButton")
        remove_profile_btn.clicked.connect(self._remove_profile)
        actions.addWidget(remove_profile_btn)

        self.eq_section.content_layout.addLayout(actions)
        self._reload_profiles()

    def _populate_details_section(self) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.enabled_check = QCheckBox("Channel enabled")
        self.enabled_check.setChecked(self.channel.enabled)
        self.enabled_check.toggled.connect(self._on_enabled_changed)
        grid.addWidget(self.enabled_check, 0, 0, 1, 2)

        self.visualizer_check = QCheckBox("Signal meter on this channel")
        self.visualizer_check.setChecked(self.channel.visualizer_enabled)
        self.visualizer_check.toggled.connect(self._on_visualizer_changed)
        grid.addWidget(self.visualizer_check, 1, 0, 1, 2)

        kind_title = QLabel("Kind")
        kind_title.setObjectName("mutedLabel")
        grid.addWidget(kind_title, 2, 0)
        grid.addWidget(QLabel(self.channel.kind.upper()), 2, 1)

        status_title = QLabel("Meter")
        status_title.setObjectName("mutedLabel")
        grid.addWidget(status_title, 3, 0)
        grid.addWidget(QLabel("Waiting for backend signal"), 3, 1)

        self.details_section.content_layout.addLayout(grid)

        if False and self.channel.key == "micro":
            self.details_section.content_layout.addWidget(QLabel("Selected inputs"))
            inputs_box = QFrame()
            inputs_box.setObjectName("appRuleRow")
            inputs_layout = QVBoxLayout(inputs_box)
            inputs_layout.setContentsMargins(8, 8, 8, 8)
            inputs_layout.setSpacing(4)

            self.mic_input_checks: list[QCheckBox] = []
            for name in MIC_INPUT_CHOICES[:-1]:
                check = QCheckBox(name)
                check.toggled.connect(self._sync_micro_inputs_from_checks)
                inputs_layout.addWidget(check)
                self.mic_input_checks.append(check)
            self.details_section.content_layout.addWidget(inputs_box)
            self._sync_micro_checks_from_target()

    def _sync_micro_checks_from_target(self) -> None:
        return

    def _sync_micro_inputs_from_checks(self) -> None:
        return



    def set_global_visualizer_enabled(self, enabled: bool) -> None:
        self.global_visualizer_enabled = enabled
        self._set_meter_visibility()

    def _current_profile(self) -> EqProfile:
        wanted = self.channel.selected_eq_profile
        for profile in self.channel.eq_profiles:
            if profile.name == wanted:
                return profile
        profile = self.channel.eq_profiles[0]
        self.channel.selected_eq_profile = profile.name
        return profile

    def _reload_profiles(self) -> None:
        if self.eq_list is None:
            return

        current_name = self.channel.selected_eq_profile or self._current_profile().name

        self.eq_list.blockSignals(True)
        self.eq_list.clear()

        selected_row = 0
        for idx, profile in enumerate(self.channel.eq_profiles):
            item = QListWidgetItem(profile.name)
            self.eq_list.addItem(item)
            if profile.name == current_name:
                selected_row = idx

        if self.eq_list.count() > 0:
            self.eq_list.setCurrentRow(selected_row)

        self.eq_list.blockSignals(False)

    def _on_eq_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        name = current.text().strip()
        if not name or name == self.channel.selected_eq_profile:
            return
        self.channel.selected_eq_profile = name
        self._emit_changed("eq_select")

    def _on_enabled_changed(self, checked: bool) -> None:
        self.channel.enabled = checked
        self._emit_changed("enabled")

    def _on_slider_pressed(self) -> None:
        self._slider_drag_active = True

    def _on_slider_released(self) -> None:
        self._slider_drag_active = False
        self.channel.volume = self.slider.value()
        self.volume_percent.setText(f"{self.channel.volume}%")
        self._emit_changed("volume_commit")

    def _on_volume_changed(self, value: int) -> None:
        self.channel.volume = value
        self.volume_percent.setText(f"{value}%")
        if self._slider_drag_active:
            self._emit_changed("volume_drag")
        else:
            self._emit_changed("volume")

    def _on_muted_changed(self, checked: bool) -> None:
        self.channel.muted = checked
        self.mute_btn.setText("Muted" if checked else "Mute")
        self._emit_changed("mute")

    def _on_visualizer_changed(self, checked: bool) -> None:
        self.channel.visualizer_enabled = checked
        self._set_meter_visibility()
        self._emit_changed("visualizer")

    def _unique_profile_name(self, wanted: str, *, preserve_current: str | None = None) -> str:
        existing = {profile.name for profile in self.channel.eq_profiles}
        if preserve_current:
            existing.discard(preserve_current)
        base = wanted.strip() or "Profile"
        if base not in existing:
            return base
        idx = 2
        while f"{base} {idx}" in existing:
            idx += 1
        return f"{base} {idx}"

    def _apply_preview_to_profile(self, target: EqProfile, preview: EqProfile) -> None:
        target.bands = copy.deepcopy(preview.bands)
        self._emit_changed("eq_preview")

    def _on_primary_target_changed(self, value: str) -> None:
        label_to_target = getattr(self, "_device_label_to_target", {})
        target = label_to_target.get(value, value)
        self.channel.primary_target = "" if target == SYSTEM_DEFAULT_CHOICE else target
        if self.device_combo is not None:
            self.device_combo.setToolTip(self.channel.primary_target or SYSTEM_DEFAULT_CHOICE)
        if self.channel.key == "micro":
            self._sync_micro_checks_from_target()
        self._emit_changed("target")

    def _add_profile(self) -> None:
        original_profiles = copy.deepcopy(self.channel.eq_profiles)
        original_selected = self.channel.selected_eq_profile

        base = "Profile"
        existing = {profile.name for profile in self.channel.eq_profiles}
        idx = 1
        while f"{base} {idx}" in existing:
            idx += 1

        temp = EqProfile.default(name=f"{base} {idx}")
        self.channel.eq_profiles.append(temp)
        self.channel.selected_eq_profile = temp.name
        self._reload_profiles()
        self._emit_changed("eq_profiles")

        dialog = EqProfileDialog(temp, self, title="Add EQ preset")
        dialog.previewChanged.connect(lambda preview: self._apply_preview_to_profile(temp, preview))

        if not dialog.exec():
            self.channel.eq_profiles = original_profiles
            self.channel.selected_eq_profile = original_selected
            self._reload_profiles()
            self._emit_changed("eq_profiles")
            return

        updated = dialog.build_profile()
        temp.name = self._unique_profile_name(updated.name)
        temp.bands = copy.deepcopy(updated.bands)
        self.channel.selected_eq_profile = temp.name
        self._reload_profiles()
        self.changed.emit()

    def _edit_profile(self) -> None:
        current = self._current_profile()
        original = copy.deepcopy(current)

        dialog = EqProfileDialog(current, self, title=f"Edit EQ preset — {current.name}")
        dialog.previewChanged.connect(lambda preview: self._apply_preview_to_profile(current, preview))

        if not dialog.exec():
            current.name = original.name
            current.bands = copy.deepcopy(original.bands)
            self.channel.selected_eq_profile = original.name
            self._reload_profiles()
            self._emit_changed("eq_profiles")
            return

        updated = dialog.build_profile()
        current.name = self._unique_profile_name(updated.name, preserve_current=original.name)
        current.bands = copy.deepcopy(updated.bands)
        self.channel.selected_eq_profile = current.name
        self._reload_profiles()
        self._emit_changed("eq_profiles")

    def _remove_profile(self) -> None:
        if len(self.channel.eq_profiles) <= 1:
            QMessageBox.information(self, "EQ preset", "At least one EQ preset must remain.")
            return

        selected = self.channel.selected_eq_profile
        answer = QMessageBox.question(
            self,
            "Delete EQ preset",
            f"Delete preset '{selected}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.channel.eq_profiles = [profile for profile in self.channel.eq_profiles if profile.name != selected]
        self.channel.selected_eq_profile = self.channel.eq_profiles[0].name
        self._reload_profiles()
        self._emit_changed("eq_profiles")
