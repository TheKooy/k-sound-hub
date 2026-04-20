from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..audio import PipeWireAudioEngine
from ..config import APP_NAME, APP_VERSION
from ..models import AppSettings
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
        self.resize(1480, 880)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.columns_host = QWidget()
        self.columns_layout = QHBoxLayout(self.columns_host)
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(10)
        self.columns_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll.setWidget(self.columns_host)

        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(10, 8, 10, 8)
        footer_layout.setSpacing(8)

        self.footer_title = QLabel(f"{APP_NAME} {APP_VERSION}")
        self.footer_title.setObjectName("mutedLabel")
        footer_layout.addWidget(self.footer_title)

        self.backend_status = QLabel(self.audio_engine.status_text())
        self.backend_status.setObjectName("mutedLabel")
        self.backend_status.setWordWrap(True)
        footer_layout.addWidget(self.backend_status, 1)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("ghostButton")
        self.settings_btn.clicked.connect(self.open_settings)
        footer_layout.addWidget(self.settings_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("ghostButton")
        self.refresh_btn.clicked.connect(self.refresh_status)
        footer_layout.addWidget(self.refresh_btn)

        root.addWidget(self.footer_bar)

        self._reload_channels()

    def _clear_columns(self) -> None:
        while self.columns_layout.count():
            item = self.columns_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.channel_widgets.clear()

    def _reload_channels(self) -> None:
        self._clear_columns()

        for channel in self.settings.channels:
            if not channel.enabled:
                continue
            widget = ChannelWidget(channel, global_visualizer_enabled=self.settings.visualizer_enabled)
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.columns_layout.addWidget(widget)

        self.columns_layout.addStretch(1)
        self.refresh_status()

    def _autosave(self) -> None:
        self.settings_store.save(self.settings)

    def _on_any_changed(self) -> None:
        self._autosave()
        self.backend_status.setText(self.audio_engine.status_text() + " • auto-saved")

    def refresh_status(self) -> None:
        enabled_channels = sum(1 for channel in self.settings.channels if channel.enabled)
        total_channels = len(self.settings.channels)
        overlay = "on" if self.settings.overlay_enabled else "off"
        visualizer = "on" if self.settings.visualizer_enabled else "off"
        self.backend_status.setText(
            self.audio_engine.status_text()
            + f" • channels: {enabled_channels}/{total_channels} • overlay: {overlay} • meter: {visualizer}"
        )
        for widget in self.channel_widgets.values():
            widget.set_global_visualizer_enabled(self.settings.visualizer_enabled)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.build_result()
            self._autosave()
            self._reload_channels()
