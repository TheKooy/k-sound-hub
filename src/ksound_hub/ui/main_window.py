from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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

from ..audio.pipewire import PipeWireAudioEngine
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
        self._pending_apply_keys: set[str] = set()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self._autosave)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(90)
        self._status_timer.timeout.connect(self.refresh_status)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._flush_pending_channel_apply)

        self._link_shared_eq_library()

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
        self.columns_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
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
        self.audio_engine.apply_settings(self.settings)
        self.refresh_status()

    def _link_shared_eq_library(self, source_channel=None) -> None:
        shared_profiles = None

        if source_channel is not None and getattr(source_channel, "eq_profiles", None):
            shared_profiles = source_channel.eq_profiles
        else:
            for channel in self.settings.channels:
                if channel.eq_profiles:
                    shared_profiles = channel.eq_profiles
                    break

        if not shared_profiles:
            return

        valid_names = {profile.name for profile in shared_profiles}
        default_name = shared_profiles[0].name

        for channel in self.settings.channels:
            channel.eq_profiles = shared_profiles
            if channel.selected_eq_profile not in valid_names:
                channel.selected_eq_profile = default_name

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_column_widths()

    def closeEvent(self, event):
        self.audio_engine.shutdown()
        super().closeEvent(event)

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
        max_spacing = 72
        base_width = max(136, min(152, (available - min_spacing * max(0, count - 1)) // count))

        for widget in widgets:
            widget.set_card_width(base_width)

        widths = [widget.width() for widget in widgets]
        total_widget_width = sum(widths)

        if count > 1:
            free_space = max(0, available - total_widget_width)
            spacing = max(min_spacing, min(max_spacing, free_space // (count - 1)))
            used = total_widget_width + spacing * (count - 1)
            remaining = max(0, available - used)
            edge_margin = remaining // 2
        else:
            spacing = 0
            edge_margin = max(0, (available - total_widget_width) // 2)

        self.columns_layout.setSpacing(spacing)
        self.columns_layout.setContentsMargins(edge_margin, 0, edge_margin, 0)
        total = total_widget_width + spacing * max(0, count - 1) + edge_margin * 2
        self.columns_host.setMinimumWidth(max(available, total))

    def _reload_channels(self) -> None:
        self._clear_columns()

        for channel in self._enabled_channels():
            widget = ChannelWidget(
                channel,
                global_visualizer_enabled=self.settings.visualizer_enabled,
                audio_engine=self.audio_engine,
                on_runtime_refresh=self.refresh_status,
            )
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.columns_layout.addWidget(widget)

        self._apply_column_widths()

    def _autosave(self) -> None:
        self.settings_store.save(self.settings)

    def _queue_channel_apply(self, channel_key: str, delay_ms: int) -> None:
        self._pending_apply_keys.add(channel_key)
        remaining = self._apply_timer.remainingTime()
        if remaining < 0 or remaining > delay_ms:
            self._apply_timer.start(delay_ms)

    def _flush_pending_channel_apply(self) -> None:
        keys = list(self._pending_apply_keys)
        self._pending_apply_keys.clear()
        for key in keys:
            self.audio_engine.apply_channel(self.settings, key)
        self._status_timer.start()

    def _on_any_changed(self) -> None:
        sender = self.sender()
        source_channel = getattr(sender, "channel", None)
        hint = getattr(sender, "_change_hint", "generic")

        self._link_shared_eq_library(source_channel=source_channel)

        if source_channel is None:
            self.audio_engine.apply_settings(self.settings)
            self._save_timer.start()
            self._status_timer.start()
            return

        if hint == "volume":
            self._queue_channel_apply(source_channel.key, 30)
        elif hint == "eq_preview":
            self._queue_channel_apply(source_channel.key, 95)
        elif hint == "mute":
            self.audio_engine.apply_channel(self.settings, source_channel.key)
            self._status_timer.start()
        else:
            self.audio_engine.apply_channel(self.settings, source_channel.key)
            self._status_timer.start()

        self._save_timer.start()

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
            widget.refresh_runtime_views()
        self._apply_column_widths()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.build_result()
            self._link_shared_eq_library()
            self._autosave()
            self._reload_channels()
            self.audio_engine.apply_settings(self.settings)
            self.refresh_status()
