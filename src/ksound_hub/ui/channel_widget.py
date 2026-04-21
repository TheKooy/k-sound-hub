from __future__ import annotations

import copy

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

DEVICE_CHOICES = {
    "playback": ["ANPW", "S/PDIF", "Temp out"],
    "monitor": ["ANPW", "S/PDIF"],
}
RETURN_MODES = ["Post-EE", "Final Mix"]
MIC_INPUT_CHOICES = ["ANPW Mic", "RODE NT-USB", "Both mics"]
PLAYBACK_CHANNEL_KEYS = {"all", "game", "chat", "media", "more"}
MIC_LINKABLE_CHANNEL_KEYS = ["all", "game", "chat", "media", "more"]


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
            return "Both mics"
        if self.channel.kind == "monitor":
            return DEVICE_CHOICES["monitor"][0]
        return DEVICE_CHOICES["playback"][0]

    def _default_secondary_target(self) -> str:
        if self.channel.key == "return-mic":
            return RETURN_MODES[0]
        return ""

    def _selector_frame(self, combo: MenuSelectorButton, *, frame_width: int = 136) -> QWidget:
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
        self.channel.primary_target = self.channel.primary_target or self._default_primary_target()
        self.channel.secondary_target = self.channel.secondary_target or self._default_secondary_target()

        if self.channel.key == "return-mic":
            box = QWidget()
            box.setAttribute(Qt.WA_TranslucentBackground, True)
            box.setAutoFillBackground(False)
            box.setStyleSheet("background: transparent;")
            outer = QHBoxLayout(box)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(8)
            outer.addStretch(1)

            self.device_combo = MenuSelectorButton()
            self.device_combo.set_items(DEVICE_CHOICES["monitor"])
            self._prepare_selector(self.device_combo)
            self._set_selector_text(self.device_combo, self.channel.primary_target)
            self.device_combo.currentTextChanged.connect(self._on_primary_target_changed)
            outer.addWidget(self._selector_frame(self.device_combo, frame_width=126), 0, Qt.AlignCenter)

            self.return_mode_combo = MenuSelectorButton()
            self.return_mode_combo.set_items(RETURN_MODES)
            self._prepare_selector(self.return_mode_combo)
            self._set_selector_text(self.return_mode_combo, self.channel.secondary_target)
            self.return_mode_combo.currentTextChanged.connect(self._on_secondary_target_changed)
            outer.addWidget(self._selector_frame(self.return_mode_combo, frame_width=126), 0, Qt.AlignCenter)

            outer.addStretch(1)
            return box

        box = QWidget()
        box.setAttribute(Qt.WA_TranslucentBackground, True)
        box.setAutoFillBackground(False)
        box.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)

        self.device_combo = MenuSelectorButton()
        if self.channel.key == "micro":
            self.device_combo.set_items(MIC_INPUT_CHOICES)
            frame_width = 140
        elif self.channel.kind == "monitor":
            self.device_combo.set_items(DEVICE_CHOICES["monitor"])
            frame_width = 130
        else:
            self.device_combo.set_items(DEVICE_CHOICES["playback"])
            frame_width = 130

        self._prepare_selector(self.device_combo)
        self._set_selector_text(self.device_combo, self.channel.primary_target)
        self.device_combo.currentTextChanged.connect(self._on_primary_target_changed)
        outer.addWidget(self._selector_frame(self.device_combo, frame_width=frame_width), 0, Qt.AlignCenter)

        outer.addStretch(1)
        return box

    def _set_selector_text(self, combo: MenuSelectorButton, value: str) -> None:
        combo.setCurrentText(value)

    def _prepare_selector(self, combo: MenuSelectorButton) -> None:
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_card_width(self, width: int) -> None:
        if self.channel.key == "return-mic":
            self._card_width = max(318, min(346, int(width) + 160))
        elif self.channel.key == "micro":
            self._card_width = max(166, min(186, int(width) + 12))
        else:
            self._card_width = max(136, min(156, int(width)))
        self.setFixedWidth(self._card_width)
        self._resize_selector_frames()

    def _resize_selector_frames(self) -> None:
        if not self._selector_frames:
            return

        if self.channel.key == "return-mic":
            available_each = max(104, (self._card_width - 32 - 8) // 2)
            for frame, base_width in self._selector_frames:
                frame.setFixedWidth(min(base_width, available_each))
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
        badge_row.addWidget(HeaderBadge("Active"))
        badge_row.addStretch(1)
        self.apps_section.content_layout.addLayout(badge_row)

        self.apps_list = QListWidget()
        self.apps_list.setMinimumHeight(96)
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

        if self.channel.key == "micro":
            item = QListWidgetItem("MIC sends temporarily disabled for stability")
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
            self.apps_list.addItem(item)
            shown += 1

        if shown == 0 and fallback_names:
            for app_name in fallback_names[:1]:
                item = QListWidgetItem(app_name)
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.apps_list.addItem(item)

    def _add_app_route(self) -> None:
        if self.channel.key == "micro":
            self._show_click_outside_message(
                "Micro sends",
                "MIC send routing is temporarily disabled in this stable build."
            )
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
        if not self.audio_engine.move_sink_input_to_channel(stream_id, self.channel.key):
            self._show_click_outside_message(
                "Apps",
                "Unable to move this app to the selected channel.",
                icon=QMessageBox.Warning,
            )
            return

        if callable(self.on_runtime_refresh):
            self.on_runtime_refresh()

    def _remove_selected_app_route(self) -> None:
        item = self.apps_list.currentItem() if self.apps_list is not None else None
        if item is None:
            return

        if self.channel.key == "micro":
            self._show_click_outside_message(
                "Micro sends",
                "MIC send routing is temporarily disabled in this stable build."
            )
            return

        if self.audio_engine is None or self.channel.key not in PLAYBACK_CHANNEL_KEYS:
            return

        stream_id = item.data(Qt.UserRole)
        if not isinstance(stream_id, int):
            return

        if self.channel.key == "all":
            self._show_click_outside_message("Apps", "This app is already on ALL.")
            return

        if not self.audio_engine.move_sink_input_to_channel(stream_id, "all"):
            self._show_click_outside_message(
                "Apps",
                "Unable to move this app back to ALL.",
                icon=QMessageBox.Warning,
            )
            return

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

        if self.channel.key == "micro":
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
        if self.channel.key != "micro" or not hasattr(self, "mic_input_checks"):
            return
        target = self.channel.primary_target or "Both mics"
        mapping = {
            "Arctis Nova Pro Mic": [True, False],
            "ANPW Mic": [True, False],
            "RODE NT-USB": [False, True],
            "Both microphones": [True, True],
            "Both mics": [True, True],
        }
        states = mapping.get(target, [True, True])
        for check, state in zip(self.mic_input_checks, states, strict=False):
            check.blockSignals(True)
            check.setChecked(state)
            check.blockSignals(False)

    def _sync_micro_inputs_from_checks(self) -> None:
        if self.channel.key != "micro" or not hasattr(self, "mic_input_checks"):
            return
        states = [check.isChecked() for check in self.mic_input_checks]
        if states == [True, False]:
            target = "ANPW Mic"
        elif states == [False, True]:
            target = "RODE NT-USB"
        elif states == [True, True]:
            target = "Both mics"
        else:
            sender = self.sender()
            if sender in self.mic_input_checks:
                sender.blockSignals(True)
                sender.setChecked(True)
                sender.blockSignals(False)
            return
        self.channel.primary_target = target
        if self.device_combo is not None:
            self._set_selector_text(self.device_combo, target)
        self._emit_changed("routing")

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

    def _on_volume_changed(self, value: int) -> None:
        self.channel.volume = value
        self.volume_percent.setText(f"{value}%")
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
        self.channel.primary_target = value
        if self.channel.key == "micro":
            self._sync_micro_checks_from_target()
        self._emit_changed("target")

    def _on_secondary_target_changed(self, value: str) -> None:
        self.channel.secondary_target = value
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
