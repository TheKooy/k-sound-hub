from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import ChannelConfig, EqBand, EqProfile
from .widgets import LevelMeterWidget


class ChannelWidget(QFrame):
    changed = Signal()

    def __init__(self, channel: ChannelConfig, global_visualizer_enabled: bool, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.global_visualizer_enabled = global_visualizer_enabled
        self.setFrameShape(QFrame.StyledPanel)

        root = QVBoxLayout(self)

        title = QLabel(channel.name)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        self.enabled_check = QCheckBox("Channel enabled")
        self.enabled_check.setChecked(channel.enabled)
        self.enabled_check.toggled.connect(self._on_enabled_changed)
        root.addWidget(self.enabled_check)

        vol_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(channel.volume)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_label = QLabel(f"{channel.volume}%")
        vol_row.addWidget(QLabel("Volume"))
        vol_row.addWidget(self.volume_slider, 1)
        vol_row.addWidget(self.volume_label)
        root.addLayout(vol_row)

        self.mute_check = QCheckBox("Muted")
        self.mute_check.setChecked(channel.muted)
        self.mute_check.toggled.connect(self._on_muted_changed)
        root.addWidget(self.mute_check)

        self.visualizer_check = QCheckBox("Visualizer enabled on this channel")
        self.visualizer_check.setChecked(channel.visualizer_enabled)
        self.visualizer_check.toggled.connect(self._on_visualizer_changed)
        root.addWidget(self.visualizer_check)

        self.meter = LevelMeterWidget()
        self.meter.setVisible(global_visualizer_enabled and channel.visualizer_enabled)
        root.addWidget(self.meter)

        eq_box = QFrame()
        eq_box.setFrameShape(QFrame.StyledPanel)
        eq_layout = QVBoxLayout(eq_box)
        eq_layout.addWidget(QLabel("EQ profiles"))

        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self._reload_profiles()
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_combo, 1)

        self.add_profile_btn = QPushButton("Add")
        self.add_profile_btn.clicked.connect(self._add_profile)
        profile_row.addWidget(self.add_profile_btn)

        self.remove_profile_btn = QPushButton("Remove")
        self.remove_profile_btn.clicked.connect(self._remove_profile)
        profile_row.addWidget(self.remove_profile_btn)

        eq_layout.addLayout(profile_row)

        self.band_list = QListWidget()
        self.band_list.currentRowChanged.connect(self._on_band_selected)
        eq_layout.addWidget(self.band_list)

        form = QFormLayout()
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.valueChanged.connect(self._update_selected_band)

        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(-24, 24)
        self.gain_spin.valueChanged.connect(self._update_selected_band)

        self.q_spin = QSpinBox()
        self.q_spin.setRange(1, 100)
        self.q_spin.valueChanged.connect(self._update_selected_band)

        form.addRow("Frequency (Hz)", self.freq_spin)
        form.addRow("Gain (dB)", self.gain_spin)
        form.addRow("Q x100", self.q_spin)
        eq_layout.addLayout(form)

        root.addWidget(eq_box)
        root.addStretch(1)

        self._reload_bands()

    def set_global_visualizer_enabled(self, enabled: bool) -> None:
        self.global_visualizer_enabled = enabled
        self.meter.setVisible(enabled and self.channel.visualizer_enabled)

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

    def _reload_bands(self) -> None:
        self.band_list.blockSignals(True)
        self.band_list.clear()
        profile = self._current_profile()
        for band in profile.bands:
            text = f"{int(band.frequency)} Hz • {band.gain_db:+.1f} dB • Q {band.q:.2f}"
            self.band_list.addItem(QListWidgetItem(text))
        self.band_list.blockSignals(False)
        if profile.bands:
            self.band_list.setCurrentRow(0)
        else:
            self._set_band_editor_enabled(False)

    def _set_band_editor_enabled(self, enabled: bool) -> None:
        self.freq_spin.setEnabled(enabled)
        self.gain_spin.setEnabled(enabled)
        self.q_spin.setEnabled(enabled)

    def _on_band_selected(self, row: int) -> None:
        profile = self._current_profile()
        if row < 0 or row >= len(profile.bands):
            self._set_band_editor_enabled(False)
            return
        band = profile.bands[row]
        self._set_band_editor_enabled(True)
        self.freq_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)
        self.q_spin.blockSignals(True)
        self.freq_spin.setValue(int(band.frequency))
        self.gain_spin.setValue(int(band.gain_db))
        self.q_spin.setValue(int(band.q * 100))
        self.freq_spin.blockSignals(False)
        self.gain_spin.blockSignals(False)
        self.q_spin.blockSignals(False)

    def _update_selected_band(self) -> None:
        profile = self._current_profile()
        row = self.band_list.currentRow()
        if row < 0 or row >= len(profile.bands):
            return
        profile.bands[row] = EqBand(
            frequency=float(self.freq_spin.value()),
            gain_db=float(self.gain_spin.value()),
            q=float(self.q_spin.value()) / 100.0,
        )
        self._reload_bands()
        self.band_list.setCurrentRow(row)
        self.changed.emit()

    def _on_enabled_changed(self, checked: bool) -> None:
        self.channel.enabled = checked
        self.changed.emit()

    def _on_volume_changed(self, value: int) -> None:
        self.channel.volume = value
        self.volume_label.setText(f"{value}%")
        self.changed.emit()

    def _on_muted_changed(self, checked: bool) -> None:
        self.channel.muted = checked
        self.changed.emit()

    def _on_visualizer_changed(self, checked: bool) -> None:
        self.channel.visualizer_enabled = checked
        self.meter.setVisible(self.global_visualizer_enabled and checked)
        self.changed.emit()

    def _on_profile_selected(self, profile_name: str) -> None:
        self.channel.selected_eq_profile = profile_name
        self._reload_bands()
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
        self._reload_bands()
        self.changed.emit()

    def _remove_profile(self) -> None:
        if len(self.channel.eq_profiles) <= 1:
            return
        selected = self.channel.selected_eq_profile
        self.channel.eq_profiles = [profile for profile in self.channel.eq_profiles if profile.name != selected]
        self.channel.selected_eq_profile = self.channel.eq_profiles[0].name
        self._reload_profiles()
        self._reload_bands()
        self.changed.emit()
