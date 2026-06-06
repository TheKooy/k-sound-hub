from __future__ import annotations

import copy

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..models import EqBand, EqProfile
from .widgets import EqBandSlider
from .window_geometry import install_window_geometry


class EqProfileDialog(QDialog):
    previewChanged = Signal(object)  # EqProfile

    def __init__(self, profile: EqProfile, parent=None, *, title: str = "Edit EQ preset"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 420)
        install_window_geometry(self, "eq_profile", default_size=(760, 420))

        self._source_profile = copy.deepcopy(profile)
        self._initial_profile = copy.deepcopy(profile)
        self._dirty = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        # Debounced live preview: avoid rebuilding/reapplying EQ on every tiny slider tick.
        # This keeps the dialog responsive and reduces audible update artifacts.
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self._emit_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.name_edit = QLineEdit(profile.name)
        self.name_edit.textChanged.connect(self._on_live_changed)
        form.addRow("Preset", self.name_edit)
        root.addLayout(form)

        hint = QLabel("10-band EQ. Gain moves in 0.5 dB steps. Double-click a frequency to edit it.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bands_wrap = QWidget()
        bands_row = QHBoxLayout(bands_wrap)
        bands_row.setContentsMargins(0, 0, 0, 0)
        bands_row.setSpacing(6)

        self.band_sliders: list[EqBandSlider] = []
        for band in profile.bands:
            slider = EqBandSlider(
                self._band_label(band.frequency),
                float(band.gain_db),
                frequency=float(band.frequency),
            )
            slider.slider.valueChanged.connect(self._on_live_changed)
            slider.frequencyChanged.connect(self._on_live_changed)
            self.band_sliders.append(slider)
            bands_row.addWidget(slider)
        root.addWidget(bands_wrap, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self._cancel_without_saving)
        root.addWidget(self.buttons)

    def _band_label(self, frequency: float) -> str:
        if frequency >= 1000:
            value = frequency / 1000
            return f"{value:g}k"
        return f"{int(frequency)}"

    def _profiles_equal(self, a: EqProfile, b: EqProfile) -> bool:
        if a.name != b.name:
            return False
        if len(a.bands) != len(b.bands):
            return False
        for ba, bb in zip(a.bands, b.bands, strict=False):
            if ba.frequency != bb.frequency or ba.gain_db != bb.gain_db or ba.q != bb.q:
                return False
        return True

    def _emit_preview(self) -> None:
        profile = self.build_profile()
        self._dirty = not self._profiles_equal(profile, self._initial_profile)
        self.previewChanged.emit(profile)

    def _on_live_changed(self, *args) -> None:
        self._preview_timer.start()

    def _cancel_without_saving(self) -> None:
        self.reject()

    def accept(self) -> None:
        if self._preview_timer.isActive():
            self._preview_timer.stop()
            self._emit_preview()
        super().accept()

    def reject(self) -> None:
        if self._preview_timer.isActive():
            self._preview_timer.stop()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        profile = self.build_profile()
        self._dirty = not self._profiles_equal(profile, self._initial_profile)

        if not self._dirty:
            event.accept()
            return

        box = QMessageBox(self)
        box.setWindowTitle("Unsaved EQ changes")
        box.setText("Save changes to this EQ preset?")
        save_btn = box.addButton("Save", QMessageBox.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is save_btn:
            event.accept()
            self.accept()
            return
        if clicked is discard_btn:
            event.accept()
            self.reject()
            return

        event.ignore()

    def build_profile(self) -> EqProfile:
        name = self.name_edit.text().strip() or self._source_profile.name
        bands: list[EqBand] = []
        for old_band, slider in zip(self._source_profile.bands, self.band_sliders, strict=False):
            bands.append(
                EqBand(
                    frequency=float(slider.frequency()),
                    gain_db=float(slider.value()),
                    q=old_band.q,
                )
            )
        return EqProfile(name=name, bands=bands)
