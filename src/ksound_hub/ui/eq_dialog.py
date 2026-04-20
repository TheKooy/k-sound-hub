from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..models import EqBand, EqProfile
from .widgets import EqBandSlider


class EqProfileDialog(QDialog):
    def __init__(self, profile: EqProfile, parent=None, *, title: str = "Edit EQ preset"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self._source_profile = profile

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.name_edit = QLineEdit(profile.name)
        form.addRow("Preset", self.name_edit)
        root.addLayout(form)

        hint = QLabel("Simple 8-band EQ. Changes are saved only when you confirm.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bands_wrap = QWidget()
        bands_row = QHBoxLayout(bands_wrap)
        bands_row.setContentsMargins(0, 0, 0, 0)
        bands_row.setSpacing(6)

        self.band_sliders: list[EqBandSlider] = []
        for band in profile.bands:
            slider = EqBandSlider(self._band_label(band.frequency), int(band.gain_db))
            self.band_sliders.append(slider)
            bands_row.addWidget(slider)
        root.addWidget(bands_wrap, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _band_label(self, frequency: float) -> str:
        if frequency >= 1000:
            value = frequency / 1000
            return f"{value:g}k"
        return f"{int(frequency)}"

    def build_profile(self) -> EqProfile:
        name = self.name_edit.text().strip() or self._source_profile.name
        bands: list[EqBand] = []
        for old_band, slider in zip(self._source_profile.bands, self.band_sliders, strict=False):
            bands.append(EqBand(frequency=old_band.frequency, gain_db=float(slider.value()), q=old_band.q))
        return EqProfile(name=name, bands=bands)
