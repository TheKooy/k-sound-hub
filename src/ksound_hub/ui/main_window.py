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
        self.resize(1440, 860)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.columns_host = QWidget()
        self.columns_layout = QHBoxLayout(self.columns_host)
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(12)
        self.columns_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.columns_host)

        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(10, 6, 10, 6)
        footer_layout.setSpacing(8)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_column_widths()

    def _clear_columns(self) -> None:
        while self.columns_layout.count():
            item = self.columns_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.channel_widgets.clear()

    def _enabled_channels(self):
        return [channel for channel in self.settings.channels if channel.enabled]

    def _apply_column_widths(self) -> None:
        widgets = list(self.channel_widgets.values())
        if not widgets:
            return

        available = max(600, self.scroll.viewport().width())
        count = len(widgets)
        min_spacing = 10
        base_width = max(138, min(156, (available - min_spacing * max(0, count - 1)) // count))

        for widget in widgets:
            widget.set_card_width(base_width)

        widths = [widget.width() for widget in widgets]
        total_widget_width = sum(widths)

        if count > 1:
            spacing = max(min_spacing, (available - total_widget_width) // (count - 1))
            spacing = min(spacing, 34)
        else:
            spacing = 0

        self.columns_layout.setSpacing(spacing)
        total = total_widget_width + spacing * max(0, count - 1)
        self.columns_host.setMinimumWidth(max(available, total))

    def _reload_channels(self) -> None:
        self._clear_columns()

        for channel in self._enabled_channels():
            widget = ChannelWidget(channel, global_visualizer_enabled=self.settings.visualizer_enabled)
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.columns_layout.addWidget(widget)

        self.refresh_status()
        self._apply_column_widths()

    def _autosave(self) -> None:
        self.settings_store.save(self.settings)

    def _on_any_changed(self) -> None:
        self._autosave()
        self.backend_status.setText(self.audio_engine.status_text())

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
        self._apply_column_widths()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.build_result()
            self._autosave()
            self._reload_channels()
