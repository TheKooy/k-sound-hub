from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..audio import PipeWireAudioEngine
from ..config import APP_NAME, APP_VERSION
from ..models import AppSettings, ChannelConfig
from ..settings_store import SettingsStore
from .channel_widget import ChannelWidget
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.audio_engine = PipeWireAudioEngine()
        self.channel_widgets: dict[str, ChannelWidget] = {}

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1200, 760)

        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        save_btn = QPushButton("Save")
        settings_btn = QPushButton("Settings")
        refresh_btn = QPushButton("Refresh backend status")
        toolbar.addWidget(save_btn)
        toolbar.addWidget(settings_btn)
        toolbar.addWidget(refresh_btn)

        save_btn.clicked.connect(self.save_settings)
        settings_btn.clicked.connect(self.open_settings)
        refresh_btn.clicked.connect(self.refresh_status)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        self.channel_list = QListWidget()
        self.channel_list.currentRowChanged.connect(self._on_channel_selected)
        layout.addWidget(self.channel_list, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        layout.addWidget(right, 1)

        self.backend_status = QLabel(self.audio_engine.status_text())
        self.backend_status.setStyleSheet("color: #aeb8c8;")
        right_layout.addWidget(self.backend_status)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        self._reload_channels()

    def _reload_channels(self) -> None:
        self.channel_list.clear()
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.channel_widgets.clear()

        for channel in self.settings.channels:
            item = QListWidgetItem(channel.name)
            item.setData(Qt.UserRole, channel.key)
            self.channel_list.addItem(item)

            widget = ChannelWidget(channel, global_visualizer_enabled=self.settings.visualizer_enabled)
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.stack.addWidget(widget)

        if self.channel_list.count() > 0:
            self.channel_list.setCurrentRow(0)

    def _on_channel_selected(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)

    def _on_any_changed(self) -> None:
        self.backend_status.setText(self.audio_engine.status_text())

    def refresh_status(self) -> None:
        self.backend_status.setText(self.audio_engine.status_text())

    def save_settings(self) -> None:
        self.settings_store.save(self.settings)
        QMessageBox.information(self, APP_NAME, "Settings saved.")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.apply_changes()
            self.settings_store.save(self.settings)
            self._reload_channels()
            for widget in self.channel_widgets.values():
                widget.set_global_visualizer_enabled(self.settings.visualizer_enabled)
            self.refresh_status()
