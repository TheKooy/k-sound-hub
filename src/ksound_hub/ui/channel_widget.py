from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QFrame,
)

from ..models import ChannelConfig, EqBand, EqProfile
from .widgets import CollapsibleSection, EqBandSlider, HeaderBadge, StereoLevelMeterWidget

CHANNEL_META = {
    "all": {"icon": "🌍", "apps": ["Default desktop audio", "Browser", "System sounds"]},
    "game": {"icon": "🎮", "apps": ["Steam game", "FMOD stream"]},
    "chat": {"icon": "💬", "apps": ["Discord voice", "Team chat"]},
    "media": {"icon": "🎵", "apps": ["Firefox media", "Music player"]},
    "more": {"icon": "🔊", "apps": ["Utility output"]},
    "micro": {"icon": "🎤", "apps": ["Voice apps", "Injected playback sends"]},
    "return-mic": {"icon": "🎧", "apps": ["Post-EasyEffects", "Final micro mix"]},
}

DEVICE_CHOICES = {
    "playback": ["Arctis Nova Pro", "USB Audio S/PDIF", "Temporary output"],
    "monitor": ["Arctis Nova Pro", "USB Audio S/PDIF"],
}

RETURN_MODES = ["Post-EasyEffects", "Final micro mix"]
MIC_INPUTS = ["Arctis Nova Pro Mic", "RODE NT-USB"]


class ChannelWidget(QFrame):
    changed = Signal()

    def __init__(self, channel: ChannelConfig, global_visualizer_enabled: bool, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.global_visualizer_enabled = global_visualizer_enabled
        self.setObjectName("channelCard")
        self.setFrameShape(QFrame.StyledPanel)
        self._card_width = 156
        self.setFixedWidth(self._card_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(7)

        meta = CHANNEL_META.get(channel.key, {"icon": "🎚️", "apps": ["No routed apps yet"]})

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(1)

        icon_label = QLabel(meta["icon"])
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 20px;")
        header.addWidget(icon_label)

        title = QLabel(channel.name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: 800;")
        header.addWidget(title)

        root.addLayout(header)

        self.device_button = QPushButton(self._device_button_text())
        self.device_button.setObjectName("deviceButton")
        self.device_button.clicked.connect(self._rotate_device_choice)
        root.addWidget(self.device_button)

        if self.channel.key == "return-mic":
            self.return_mode_button = QPushButton(RETURN_MODES[0])
            self.return_mode_button.setObjectName("deviceButton")
            self.return_mode_button.clicked.connect(self._toggle_return_mode)
            root.addWidget(self.return_mode_button)
        else:
            self.return_mode_button = None

        self.volume_percent = QLabel(f"{self.channel.volume}%")
        self.volume_percent.setAlignment(Qt.AlignCenter)
        self.volume_percent.setStyleSheet("font-size: 15px; font-weight: 800;")
        root.addWidget(self.volume_percent)

        self.left_meter = StereoLevelMeterWidget("L")
        self.right_meter = StereoLevelMeterWidget("R")

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(6)
        slider_row.addStretch(1)
        slider_row.addWidget(self.left_meter, 0, Qt.AlignBottom)

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(channel.volume)
        self.slider.valueChanged.connect(self._on_volume_changed)
        self.slider.setFixedHeight(160)
        slider_row.addWidget(self.slider, 0, Qt.AlignHCenter)

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

    def set_card_width(self, width: int) -> None:
        self._card_width = max(142, min(168, int(width)))
        self.setFixedWidth(self._card_width)

    def _set_meter_visibility(self) -> None:
        visible = self.global_visualizer_enabled and self.channel.visualizer_enabled
        self.left_meter.setVisible(visible)
        self.right_meter.setVisible(visible)

    def _device_button_text(self) -> str:
        if self.channel.key == "micro":
            return "2 inputs selected"
        return "Arctis Nova Pro"

    def _rotate_device_choice(self) -> None:
        if self.channel.key == "micro":
            choices = ["1 input selected", "2 inputs selected"]
            current = self.device_button.text()
            idx = (choices.index(current) + 1) % len(choices) if current in choices else 0
            self.device_button.setText(choices[idx])
        else:
            choices = DEVICE_CHOICES.get(self.channel.kind, DEVICE_CHOICES["playback"])
            current = self.device_button.text()
            idx = (choices.index(current) + 1) % len(choices) if current in choices else 0
            picked = choices[idx]
            self.device_button.setText(picked)
        self.changed.emit()

    def _toggle_return_mode(self) -> None:
        if self.return_mode_button is None:
            return
        current = self.return_mode_button.text()
        idx = (RETURN_MODES.index(current) + 1) % len(RETURN_MODES)
        self.return_mode_button.setText(RETURN_MODES[idx])
        self.changed.emit()

    def _populate_apps_section(self, app_names: list[str]) -> None:
        badge_row = QHBoxLayout()
        badge_row.addWidget(HeaderBadge("Active"))
        badge_row.addStretch(1)
        self.apps_section.content_layout.addLayout(badge_row)

        app_list = QListWidget()
        app_list.setMinimumHeight(96)
        for app_name in app_names:
            app_list.addItem(QListWidgetItem(app_name))
        self.apps_section.content_layout.addWidget(app_list)

        actions = QHBoxLayout()
        add_btn = QPushButton("+")
        add_btn.setObjectName("tinyButton")
        remove_btn = QPushButton("🗑")
        remove_btn.setObjectName("tinyButton")
        actions.addWidget(add_btn)
        actions.addStretch(1)
        actions.addWidget(remove_btn)
        self.apps_section.content_layout.addLayout(actions)

    def _populate_eq_section(self) -> None:
        top_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self._reload_profiles()
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        top_row.addWidget(self.profile_combo, 1)

        add_profile_btn = QPushButton("+")
        add_profile_btn.setObjectName("tinyButton")
        add_profile_btn.clicked.connect(self._add_profile)
        top_row.addWidget(add_profile_btn)

        remove_profile_btn = QPushButton("−")
        remove_profile_btn.setObjectName("tinyButton")
        remove_profile_btn.clicked.connect(self._remove_profile)
        top_row.addWidget(remove_profile_btn)

        self.eq_section.content_layout.addLayout(top_row)

        bands_row = QHBoxLayout()
        bands_row.setSpacing(5)
        self.band_sliders: list[EqBandSlider] = []
        profile = self._current_profile()
        for band in profile.bands:
            slider = EqBandSlider(self._band_label(band.frequency), int(band.gain_db))
            slider.slider.valueChanged.connect(self._update_bands_from_ui)
            self.band_sliders.append(slider)
            bands_row.addWidget(slider)
        self.eq_section.content_layout.addLayout(bands_row)

        advanced_row = QHBoxLayout()
        advanced_row.addWidget(HeaderBadge("Simple EQ"))
        advanced_row.addStretch(1)
        adv_btn = QPushButton("Advanced later")
        adv_btn.setObjectName("titleButton")
        adv_btn.setEnabled(False)
        advanced_row.addWidget(adv_btn)
        self.eq_section.content_layout.addLayout(advanced_row)

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
            inputs = QListWidget()
            inputs.setMinimumHeight(68)
            for name in MIC_INPUTS:
                item = QListWidgetItem(name)
                inputs.addItem(item)
            self.details_section.content_layout.addWidget(QLabel("Micro inputs"))
            self.details_section.content_layout.addWidget(inputs)

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
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.channel.eq_profiles:
            self.profile_combo.addItem(profile.name)
        index = max(0, self.profile_combo.findText(self.channel.selected_eq_profile))
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

    def _band_label(self, frequency: float) -> str:
        if frequency >= 1000:
            return f"{int(frequency / 1000)}k"
        return f"{int(frequency)}"

    def _update_bands_from_ui(self) -> None:
        profile = self._current_profile()
        if len(profile.bands) != len(self.band_sliders):
            return
        new_bands: list[EqBand] = []
        for old_band, slider in zip(profile.bands, self.band_sliders, strict=False):
            new_bands.append(EqBand(frequency=old_band.frequency, gain_db=float(slider.value()), q=old_band.q))
        profile.bands = new_bands
        self.changed.emit()

    def _on_enabled_changed(self, checked: bool) -> None:
        self.channel.enabled = checked
        self.changed.emit()

    def _on_volume_changed(self, value: int) -> None:
        self.channel.volume = value
        self.volume_percent.setText(f"{value}%")
        self.changed.emit()

    def _on_muted_changed(self, checked: bool) -> None:
        self.channel.muted = checked
        self.mute_btn.setText("Muted" if checked else "Mute")
        self.changed.emit()

    def _on_visualizer_changed(self, checked: bool) -> None:
        self.channel.visualizer_enabled = checked
        self._set_meter_visibility()
        self.changed.emit()

    def _on_profile_selected(self, profile_name: str) -> None:
        self.channel.selected_eq_profile = profile_name
        profile = self._current_profile()
        for slider, band in zip(self.band_sliders, profile.bands, strict=False):
            slider.setValue(int(band.gain_db))
        self.changed.emit()

    def _add_profile(self) -> None:
        base = "Profile"
        existing = {profile.name for profile in self.channel.eq_profiles}
        idx = 1
        while f"{base} {idx}" in existing:
            idx += 1
        new_profile = EqProfile.default(name=f"{base} {idx}")
        self.channel.eq_profiles.append(new_profile)
        self.channel.selected_eq_profile = new_profile.name
        self._reload_profiles()
        self._on_profile_selected(new_profile.name)
        self.changed.emit()

    def _remove_profile(self) -> None:
        if len(self.channel.eq_profiles) <= 1:
            return
        selected = self.channel.selected_eq_profile
        self.channel.eq_profiles = [profile for profile in self.channel.eq_profiles if profile.name != selected]
        self.channel.selected_eq_profile = self.channel.eq_profiles[0].name
        self._reload_profiles()
        self._on_profile_selected(self.channel.selected_eq_profile)
        self.changed.emit()
