from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import AppSettings, ChannelConfig


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings

        root = QVBoxLayout(self)

        self.overlay_check = QCheckBox("Enable overlay")
        self.overlay_check.setChecked(settings.overlay_enabled)
        root.addWidget(self.overlay_check)

        self.visualizer_check = QCheckBox("Enable visualizer widgets")
        self.visualizer_check.setChecked(settings.visualizer_enabled)
        root.addWidget(self.visualizer_check)

        root.addWidget(QLabel("Channels"))
        self.channel_list = QListWidget()
        root.addWidget(self.channel_list)

        row = QHBoxLayout()
        self.add_btn = QPushButton("Add channel")
        self.remove_btn = QPushButton("Remove selected")
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        root.addLayout(row)

        self.add_btn.clicked.connect(self._add_channel)
        self.remove_btn.clicked.connect(self._remove_selected)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload()

    def _reload(self) -> None:
        self.channel_list.clear()
        for channel in self.settings.channels:
            item = QListWidgetItem(f"{channel.name} ({channel.kind})")
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
        if row < 0:
            return
        if row >= len(self.settings.channels):
            return
        self.settings.channels.pop(row)
        self._reload()

    def apply_changes(self) -> None:
        self.settings.overlay_enabled = self.overlay_check.isChecked()
        self.settings.visualizer_enabled = self.visualizer_check.isChecked()
