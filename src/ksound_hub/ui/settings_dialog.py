from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ..models import AppSettings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent=None,
        *,
        wallpaper_preview_callback=None,
        wallpaper_reset_callback=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("K-Sound Hub Settings")
        self.settings = copy.deepcopy(settings)
        self._wallpaper_preview_callback = wallpaper_preview_callback
        self._wallpaper_reset_callback = wallpaper_reset_callback
        self.resize(620, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("Global settings")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.overlay_check = QCheckBox("Enable overlay")
        self.overlay_check.setChecked(self.settings.overlay_enabled)
        root.addWidget(self.overlay_check)

        self.visualizer_check = QCheckBox("Enable signal meter widgets")
        self.visualizer_check.setChecked(self.settings.visualizer_enabled)
        root.addWidget(self.visualizer_check)

        self.close_to_tray_check = QCheckBox("Clicking the window close button sends the app to the tray")
        self.close_to_tray_check.setChecked(bool(getattr(self.settings, "close_to_tray", True)))
        root.addWidget(self.close_to_tray_check)

        self.wallpaper_check = QCheckBox("Enable wallpaper background")
        self.wallpaper_check.setChecked(self.settings.wallpaper_enabled)
        root.addWidget(self.wallpaper_check)

        wallpaper_file_title = QLabel("Wallpaper file")
        wallpaper_file_title.setObjectName("mutedLabel")
        root.addWidget(wallpaper_file_title)

        wallpaper_path_row = QHBoxLayout()
        wallpaper_path_row.setSpacing(6)

        self.wallpaper_path_edit = QLineEdit(self.settings.wallpaper_path)
        self.wallpaper_path_edit.setPlaceholderText("/path/to/wallpaper.png")
        wallpaper_path_row.addWidget(self.wallpaper_path_edit, 1)

        self.wallpaper_browse_btn = QPushButton("Browse")
        wallpaper_path_row.addWidget(self.wallpaper_browse_btn)

        self.wallpaper_clear_btn = QPushButton("Clear")
        wallpaper_path_row.addWidget(self.wallpaper_clear_btn)

        root.addLayout(wallpaper_path_row)

        wallpaper_blur_title = QLabel("Wallpaper blur")
        wallpaper_blur_title.setObjectName("mutedLabel")
        root.addWidget(wallpaper_blur_title)

        self.wallpaper_blur_slider = QSlider(Qt.Horizontal)
        self.wallpaper_blur_slider.setRange(0, 32)
        self.wallpaper_blur_slider.setValue(int(self.settings.wallpaper_blur))
        root.addWidget(self.wallpaper_blur_slider)

        self.wallpaper_blur_value = QLabel()
        self.wallpaper_blur_value.setObjectName("mutedLabel")
        self.wallpaper_blur_value.setAlignment(Qt.AlignRight)
        root.addWidget(self.wallpaper_blur_value)

        wallpaper_tint_title = QLabel("Wallpaper dark overlay")
        wallpaper_tint_title.setObjectName("mutedLabel")
        root.addWidget(wallpaper_tint_title)

        self.wallpaper_tint_slider = QSlider(Qt.Horizontal)
        self.wallpaper_tint_slider.setRange(0, 100)
        self.wallpaper_tint_slider.setValue(int(self.settings.wallpaper_tint_strength))
        root.addWidget(self.wallpaper_tint_slider)

        self.wallpaper_tint_value = QLabel()
        self.wallpaper_tint_value.setObjectName("mutedLabel")
        self.wallpaper_tint_value.setAlignment(Qt.AlignRight)
        root.addWidget(self.wallpaper_tint_value)

        hint = QLabel("Channel changes are stored immediately in global settings.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(QLabel("Channels"))
        self.channel_list = QListWidget()
        root.addWidget(self.channel_list, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add channel")
        self.remove_btn = QPushButton("Remove selected")
        self.toggle_btn = QPushButton("Toggle enabled")
        row.addWidget(self.add_btn)
        row.addWidget(self.toggle_btn)
        row.addStretch(1)
        row.addWidget(self.remove_btn)
        root.addLayout(row)

        self.add_btn.clicked.connect(self._add_channel)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.toggle_btn.clicked.connect(self._toggle_selected)

        self.wallpaper_check.toggled.connect(self._on_wallpaper_inputs_changed)
        self.wallpaper_path_edit.textChanged.connect(self._on_wallpaper_inputs_changed)
        self.wallpaper_browse_btn.clicked.connect(self._browse_wallpaper)
        self.wallpaper_clear_btn.clicked.connect(self._clear_wallpaper)
        self.wallpaper_blur_slider.valueChanged.connect(self._on_wallpaper_inputs_changed)
        self.wallpaper_tint_slider.valueChanged.connect(self._on_wallpaper_inputs_changed)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload()
        self._on_wallpaper_inputs_changed()

    def _reload(self) -> None:
        self.channel_list.clear()
        for channel in self.settings.channels:
            state = "enabled" if channel.enabled else "disabled"
            item = QListWidgetItem(f"{channel.name} ({channel.kind}) • {state}")
            item.setData(Qt.UserRole, channel.key)
            self.channel_list.addItem(item)

    def _add_channel(self) -> None:
        base = "custom"
        idx = 1
        existing = {channel.key for channel in self.settings.channels}
        while f"{base}-{idx}" in existing:
            idx += 1
        key = f"{base}-{idx}"
        channel = ChannelConfig(key=key, name=f"CUSTOM {idx}", kind="playback")
        self.settings.channels.append(channel)
        self._reload()

    def _remove_selected(self) -> None:
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self.settings.channels):
            return
        self.settings.channels.pop(row)
        self._reload()

    def _toggle_selected(self) -> None:
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self.settings.channels):
            return
        self.settings.channels[row].enabled = not self.settings.channels[row].enabled
        self._reload()

    def _browse_wallpaper(self) -> None:
        current = self.wallpaper_path_edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select wallpaper",
            current,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if path:
            self.wallpaper_path_edit.setText(path)

    def _clear_wallpaper(self) -> None:
        self.wallpaper_path_edit.clear()

    def _sync_wallpaper_fields_to_settings(self) -> None:
        self.settings.wallpaper_enabled = self.wallpaper_check.isChecked()
        self.settings.wallpaper_path = self.wallpaper_path_edit.text().strip()
        self.settings.wallpaper_blur = int(self.wallpaper_blur_slider.value())
        self.settings.wallpaper_tint_strength = int(self.wallpaper_tint_slider.value())

    def _update_wallpaper_labels(self) -> None:
        self.wallpaper_blur_value.setText(f"Blur: {self.wallpaper_blur_slider.value()} px")
        self.wallpaper_tint_value.setText(f"Dark overlay: {self.wallpaper_tint_slider.value()}%")

    def _update_wallpaper_controls(self) -> None:
        enabled = self.wallpaper_check.isChecked()
        for widget in (
            self.wallpaper_path_edit,
            self.wallpaper_browse_btn,
            self.wallpaper_clear_btn,
            self.wallpaper_blur_slider,
            self.wallpaper_tint_slider,
        ):
            widget.setEnabled(enabled)
        self.wallpaper_blur_value.setEnabled(enabled)
        self.wallpaper_tint_value.setEnabled(enabled)

    def _on_wallpaper_inputs_changed(self) -> None:
        self._update_wallpaper_labels()
        self._update_wallpaper_controls()
        self._sync_wallpaper_fields_to_settings()
        if callable(self._wallpaper_preview_callback):
            self._wallpaper_preview_callback(self.settings)

    def reject(self) -> None:
        if callable(self._wallpaper_reset_callback):
            self._wallpaper_reset_callback()
        super().reject()

    def build_result(self) -> AppSettings:
        self.settings.overlay_enabled = self.overlay_check.isChecked()
        self.settings.visualizer_enabled = self.visualizer_check.isChecked()
        self.settings.close_to_tray = self.close_to_tray_check.isChecked()
        self._sync_wallpaper_fields_to_settings()
        return self.settings
