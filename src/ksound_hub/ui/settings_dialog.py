from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..models import AppSettings, ChannelConfig


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("K-Sound Hub Settings")
        self.settings = settings
        self.resize(520, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("Global settings")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.overlay_check = QCheckBox("Enable overlay")
        self.overlay_check.setChecked(settings.overlay_enabled)
        root.addWidget(self.overlay_check)

        self.visualizer_check = QCheckBox("Enable visualizer widgets")
        self.visualizer_check.setChecked(settings.visualizer_enabled)
        root.addWidget(self.visualizer_check)

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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload()

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

    def apply_changes(self) -> None:
        self.settings.overlay_enabled = self.overlay_check.isChecked()
        self.settings.visualizer_enabled = self.visualizer_check.isChecked()
