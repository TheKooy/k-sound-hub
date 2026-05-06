from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..audio.pipewire_v2_final import PipeWireAudioEngine
from ..config import APP_ICON_PATH, APP_NAME, IPC_SOCKET_PATH
from ..ipc import AudioIpcServer
from ..settings_store import SettingsStore
from .channel_widget import ChannelWidget
from .overlay import OverlayManager
from .settings_dialog import SettingsDialog
from .soundboard_dialog import SoundboardDialog
from .window_geometry import install_window_geometry


CHANNEL_OVERLAY_META = {
    "all": ("🌍", "ALL"),
    "game": ("🎮", "GAME"),
    "chat": ("💬", "CHAT"),
    "media": ("🎵", "MEDIA"),
    "more": ("🔊", "MORE"),
    "micro": ("🎤", "MICRO"),
    "return-mic": ("🎧", "MIC OUT"),
}

CHANNEL_KEY_ALIASES = {
    "all": "all",
    "game": "game",
    "chat": "chat",
    "media": "media",
    "more": "more",
    "micro": "micro",
    "retour": "return-mic",
    "retourmic": "return-mic",
    "return-mic": "return-mic",
    "return_mic": "return-mic",
}


class MainWindow(QMainWindow):
    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.audio_engine = PipeWireAudioEngine()
        self.channel_widgets: dict[str, ChannelWidget] = {}
        self.soundboard_dialog: SoundboardDialog | None = None
        self._pending_apply_keys: set[str] = set()

        self._force_close = False
        self._tray_message_shown = False
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self._autosave)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(250)
        self._status_timer.timeout.connect(self.refresh_status)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._flush_pending_channel_apply)

        self._runtime_view_timer = QTimer(self)
        self._runtime_view_timer.setSingleShot(True)
        self._runtime_view_timer.setInterval(90)
        self._runtime_view_timer.timeout.connect(self._refresh_runtime_views_only)

        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(100)
        self._meter_timer.timeout.connect(self._refresh_meters)

        self._link_shared_eq_library()

        self.overlay = OverlayManager(self)
        self.overlay.set_enabled(self.settings.overlay_enabled)

        self.ipc_server = AudioIpcServer(IPC_SOCKET_PATH, self)
        self.ipc_server.message_received.connect(self.handle_ipc_message)
        self.ipc_server.start()

        self.setWindowTitle(APP_NAME)
        if APP_ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1440, 860)

        self._wallpaper_source = QPixmap()

        central = QWidget()
        central.setObjectName("centralStack")
        self.setCentralWidget(central)

        stack = QStackedLayout(central)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackAll)

        self.background_base = QWidget()
        self.background_base.setObjectName("backgroundBase")

        self.background_label = QLabel(self.background_base)
        self.background_label.setObjectName("wallpaperLabel")
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.background_label.hide()

        self.background_blur = QGraphicsBlurEffect(self.background_label)
        self.background_blur.setBlurHints(QGraphicsBlurEffect.PerformanceHint)
        self.background_label.setGraphicsEffect(self.background_blur)

        self.background_tint = QFrame(self.background_base)
        self.background_tint.setObjectName("wallpaperTint")
        self.background_tint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.background_tint.hide()

        foreground = QWidget()
        foreground.setObjectName("mainRoot")

        stack.addWidget(self.background_base)
        stack.addWidget(foreground)
        stack.setCurrentWidget(foreground)

        root = QVBoxLayout(foreground)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("scrollViewport")
        self.scroll.viewport().setAutoFillBackground(False)
        root.addWidget(self.scroll, 1)

        self.columns_host = QWidget()
        self.columns_host.setObjectName("columnsHost")
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

        self.soundboard_btn = QPushButton("Soundboard")
        self.soundboard_btn.setObjectName("ghostButton")
        self.soundboard_btn.clicked.connect(self.open_soundboard)
        footer_layout.addWidget(self.soundboard_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("ghostButton")
        self.settings_btn.clicked.connect(self.open_settings)
        footer_layout.addWidget(self.settings_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("ghostButton")
        self.refresh_btn.clicked.connect(self.refresh_status)
        footer_layout.addWidget(self.refresh_btn)

        root.addWidget(self.footer_bar)

        self._apply_wallpaper_settings()
        self._update_background_layers()

        self._normalize_app_rules()
        self._reload_channels()
        self.audio_engine.apply_settings(self.settings)
        self._reapply_saved_app_routes()
        self.refresh_status()
        self._meter_timer.start()

        self._schedule_startup_visual_refresh()

        QApplication.instance().installEventFilter(self)

        install_window_geometry(self, "main", default_size=(1440, 860))

        # Install geometry restore only after the full main UI has been built.
        # Subwindows already work because they are opened after startup.
        install_window_geometry(self, "main", default_size=(1440, 860))

    def eventFilter(self, obj, event) -> bool:
        """Reserve mouse-wheel scrolling for the main Hub page only.

        Manual sliders/scrollbars still work. Only wheel/touchpad wheel events
        are intercepted inside the main window.
        """
        if event.type() != QEvent.Wheel:
            return super().eventFilter(obj, event)

        if not isinstance(obj, QWidget):
            return super().eventFilter(obj, event)

        if obj.window() is not self:
            return super().eventFilter(obj, event)

        if not hasattr(self, "scroll"):
            return super().eventFilter(obj, event)

        bar = self.scroll.verticalScrollBar()
        if bar is None or bar.maximum() <= bar.minimum():
            event.accept()
            return True

        angle = event.angleDelta()
        pixel = event.pixelDelta()

        if pixel.y():
            step = -pixel.y()
        elif angle.y():
            step = int(-(angle.y() / 120.0) * bar.singleStep() * 3)
        else:
            # Horizontal wheel/touchpad movement: swallow it. It should not
            # move Apps/EQ/list internals horizontally.
            event.accept()
            return True

        if step:
            bar.setValue(bar.value() + step)

        event.accept()
        return True

    def _schedule_startup_runtime_refresh(self) -> None:
        """Resync routing and UI after cold start.

        Some app streams appear after the first UI build. Without delayed
        passes, the Apps section can display a stream in one channel while
        PipeWire still routes it through another one until Refresh is pressed.
        """
        for delay in (250, 800, 1600, 3200, 5200, 8000):
            QTimer.singleShot(delay, self._startup_runtime_refresh_once)

    def _startup_runtime_refresh_once(self) -> None:
        try:
            self._normalize_app_rules()
            self._reapply_saved_app_routes()
            self.refresh_status()

            # Also refresh size-dependent UI. This is intentionally repeated:
            # at startup the window/background can still be settling.
            if hasattr(self, "_startup_visual_refresh_once"):
                self._startup_visual_refresh_once()
            else:
                self._update_background_layers()
                self._apply_column_widths()
                self.update()
        except RuntimeError:
            pass

    def _schedule_startup_visual_refresh(self) -> None:
        """Refresh size-dependent UI once the window has its real size.

        At cold start, the wallpaper and channel spacing can be calculated
        before Qt has applied the final window geometry. A few delayed passes
        reproduce what a manual resize/Refresh already fixes.
        """
        for delay in (0, 60, 180, 420, 900):
            QTimer.singleShot(delay, self._startup_visual_refresh_once)

    def _startup_visual_refresh_once(self) -> None:
        try:
            self.scroll.updateGeometry()
            self.columns_host.updateGeometry()
            self.columns_layout.invalidate()
            self._apply_column_widths()
            self._update_background_layers()

            if self.scroll.widget() is not None:
                self.scroll.widget().updateGeometry()

            self.scroll.viewport().update()
            self.update()
        except RuntimeError:
            pass

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

    def _find_channel(self, key: str):
        for channel in self.settings.channels:
            if channel.key == key:
                return channel
        return None

    def _normalize_app_rules(self) -> None:
        priority = ["game", "chat", "media", "more", "all"]
        seen: dict[str, str] = {}

        channels = {channel.key: channel for channel in self.settings.channels}
        for key in priority:
            channel = channels.get(key)
            if channel is None:
                continue

            cleaned: list[str] = []
            for rule in channel.app_rules:
                rule = str(rule or "").strip()
                if not rule:
                    continue

                owner = seen.get(rule)
                if owner is None:
                    seen[rule] = key
                    cleaned.append(rule)
                    continue

                if owner == "all" and key != "all":
                    all_channel = channels.get("all")
                    if all_channel is not None:
                        all_channel.app_rules = [r for r in all_channel.app_rules if r != rule]
                    seen[rule] = key
                    cleaned.append(rule)

            channel.app_rules = cleaned

    def _prefer_app_rules_for_channel(self, preferred_channel) -> None:
        """Make moved app rules belong to the target channel only.

        When an app is moved from GAME to MEDIA, the old bin/app rule must be
        removed from GAME, otherwise startup route restore may send it back to
        the older channel.
        """
        if preferred_channel is None:
            return

        if preferred_channel.key not in {"all", "game", "chat", "media", "more"}:
            return

        preferred_rules = {
            str(rule or "").strip()
            for rule in getattr(preferred_channel, "app_rules", []) or []
            if str(rule or "").strip()
        }
        if not preferred_rules:
            return

        for channel in self.settings.channels:
            if channel is preferred_channel:
                continue
            if channel.key not in {"all", "game", "chat", "media", "more"}:
                continue

            channel.app_rules = [
                rule for rule in getattr(channel, "app_rules", []) or []
                if str(rule or "").strip() not in preferred_rules
            ]

    def _stream_matches_rule(self, stream, rule: str) -> bool:
        rule = str(rule or "").strip()
        if not rule:
            return False
        if rule.startswith("bin:"):
            return bool(getattr(stream, "binary_name", "")) and stream.binary_name == rule[4:]
        if rule.startswith("app:"):
            return bool(getattr(stream, "app_name", "")) and stream.app_name == rule[4:]
        return False

    def _reapply_saved_app_routes(self) -> None:
        streams = self.audio_engine.list_sink_inputs()
        for channel in self.settings.channels:
            if channel.key not in {"all", "game", "chat", "media", "more"}:
                continue
            rules = list(getattr(channel, "app_rules", []) or [])
            if not rules:
                continue
            for stream in streams:
                if stream.sink_name == channel.key:
                    continue
                if any(self._stream_matches_rule(stream, rule) for rule in rules):
                    self.audio_engine.move_sink_input_to_channel(stream.stream_id, channel.key)

    def _normalize_channel_key(self, value: str) -> str:
        raw = str(value or "").strip().lower().replace(" ", "-")
        return CHANNEL_KEY_ALIASES.get(raw, raw)

    def _overlay_text(self, channel, hint: str) -> str:
        icon, label = CHANNEL_OVERLAY_META.get(channel.key, ("🎚", channel.name))
        if hint == "mute":
            return f"{icon} {label} {'🔇' if channel.muted else '🔊'}"
        return f"{icon} {label} {channel.volume}%"


    def _show_overlay_for_change(self, channel, hint: str) -> None:
        if hint not in {"volume", "mute"}:
            return
        self.overlay.show_message(
            self._overlay_text(channel, hint),
            muted_active=(hint == "mute" and bool(channel.muted)),
        )


    def _sync_widget_for_channel(self, channel_key: str) -> None:
        widget = self.channel_widgets.get(channel_key)
        channel = self._find_channel(channel_key)
        if widget is None or channel is None:
            return

        widget.slider.blockSignals(True)
        widget.slider.setValue(int(channel.volume))
        widget.slider.blockSignals(False)
        widget.volume_percent.setText(f"{channel.volume}%")

        widget.mute_btn.blockSignals(True)
        widget.mute_btn.setChecked(bool(channel.muted))
        widget.mute_btn.setText("Muted" if channel.muted else "Mute")
        widget.mute_btn.blockSignals(False)

    def handle_ipc_message(self, payload: dict) -> None:
        command = str(payload.get("command", "")).strip().lower()
        if command == "restore":
            self._restore_from_tray()
            return

        if command in {"soundboard-stop-all", "soundboard_stop_all"}:
            dialog = self._ensure_soundboard_dialog()
            dialog.stop_all()
            return

        if command in {"soundboard-set-global-volume", "soundboard_set_global_volume"}:
            dialog = self._ensure_soundboard_dialog()
            dialog.set_global_volume(payload.get("volume"))
            return

        if command in {"soundboard-move-slot", "soundboard_move_slot"}:
            slot = str(payload.get("slot") or payload.get("id") or payload.get("label") or "")
            direction = str(payload.get("direction") or "")
            dialog = self._ensure_soundboard_dialog()
            dialog.move_slot_by_key(slot, direction)
            return

        if command in {"soundboard-reorder-slots", "soundboard_reorder_slots"}:
            order = payload.get("order")
            dialog = self._ensure_soundboard_dialog()
            dialog.reorder_slots_by_ids(order if isinstance(order, list) else [])
            return

        if command in {"soundboard", "soundboard-play", "soundboard_play"}:
            slot = str(payload.get("slot") or payload.get("id") or payload.get("label") or "")
            dialog = self._ensure_soundboard_dialog()
            dialog.play_slot_by_key(slot)
            return

        channel_key = self._normalize_channel_key(payload.get("channel", ""))
        channel = self._find_channel(channel_key)
        if channel is None:
            return

        action = str(payload.get("action", "")).strip().lower()
        hint = "generic"
        changed = False

        if action in {"volup", "voldown", "set-volume"} and channel.muted:
            self._sync_widget_for_channel(channel.key)
            self._show_overlay_for_change(channel, "mute")
            return

        if action == "volup":
            channel.volume = min(100, int(channel.volume) + 5)
            hint = "volume"
            changed = True
        elif action == "voldown":
            channel.volume = max(0, int(channel.volume) - 5)
            hint = "volume"
            changed = True
        elif action == "mute":
            channel.muted = not bool(channel.muted)
            hint = "mute"
            changed = True
        elif action == "set-volume":
            try:
                channel.volume = max(0, min(100, int(payload.get("volume", channel.volume))))
            except Exception:
                return
            hint = "volume"
            changed = True

        if not changed:
            return

        self._sync_widget_for_channel(channel.key)
        self._show_overlay_for_change(channel, hint)

        if hint == "volume":
            self._apply_channel_volume_fast(channel.key)
        else:
            self.audio_engine.apply_channel(self.settings, channel.key)
            self._status_timer.start()

        self._save_timer.start()

    def _can_close_to_tray(self) -> bool:
        return bool(self.settings.close_to_tray) and QSystemTrayIcon.isSystemTrayAvailable()

    def _ensure_tray_icon(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False

        if self.tray_icon is not None:
            return True

        icon = QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.is_file() else self.windowIcon()
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip(APP_NAME)
        tray.activated.connect(self._on_tray_activated)

        menu = QMenu(self)
        restore_action = menu.addAction("Restore")
        restore_action.triggered.connect(self._restore_from_tray)

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_from_tray)

        tray.setContextMenu(menu)

        self.tray_icon = tray
        self.tray_menu = menu
        return True

    def _present_window(self) -> None:
        self.setVisible(True)
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            self.setFocus(Qt.ActiveWindowFocusReason)
        except Exception:
            pass

    def _restore_from_tray(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self._present_window()
        QTimer.singleShot(0, self._present_window)
        QTimer.singleShot(150, self._present_window)


    def _quit_from_tray(self) -> None:
        self._force_close = True
        if self.tray_icon is not None:
            self.tray_icon.hide()
            try:
                self.tray_icon.deleteLater()
            except Exception:
                pass
            self.tray_icon = None
        self.close()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
            QTimer.singleShot(150, app.quit)


    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
            QSystemTrayIcon.MiddleClick,
        ):
            self._restore_from_tray()

    def _update_background_layers(self) -> None:
        rect = self.background_base.rect()
        self.background_label.setGeometry(rect)
        self.background_tint.setGeometry(rect)
        self._refresh_wallpaper_pixmap()

    def _refresh_wallpaper_pixmap(self) -> None:
        if self._wallpaper_source.isNull():
            self.background_label.clear()
            return

        size = self.background_label.size()
        if size.width() <= 0 or size.height() <= 0:
            return

        scaled = self._wallpaper_source.scaled(
            size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.background_label.setPixmap(scaled)

    def _apply_wallpaper_settings(self, settings=None) -> None:
        active_settings = self.settings if settings is None else settings
        enabled = bool(getattr(active_settings, "wallpaper_enabled", False))
        path = str(getattr(active_settings, "wallpaper_path", "") or "").strip()
        valid = enabled and path and Path(path).is_file()

        if valid:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                valid = False
            else:
                self._wallpaper_source = pixmap

        if not valid:
            self._wallpaper_source = QPixmap()
            self.background_label.clear()
            self.background_label.hide()
            self.background_tint.hide()
            self.background_tint.setStyleSheet("background: transparent;")
            return

        blur = max(0, min(32, int(getattr(active_settings, "wallpaper_blur", 0))))
        tint = max(0, min(100, int(getattr(active_settings, "wallpaper_tint_strength", 0))))
        alpha = int(180 * (tint / 100.0))

        self.background_blur.setBlurRadius(float(blur))
        self.background_tint.setStyleSheet(f"background: rgba(0, 0, 0, {alpha});")
        self.background_label.show()
        self.background_tint.show()
        self._update_background_layers()

    def _preview_wallpaper_settings(self, preview_settings) -> None:
        self._apply_wallpaper_settings(preview_settings)

    def _restore_wallpaper_preview(self) -> None:
        self._apply_wallpaper_settings(self.settings)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_background_layers()
        self._apply_column_widths()

    def closeEvent(self, event):
        if not self._force_close and self._can_close_to_tray() and self._ensure_tray_icon():
            event.ignore()
            self.hide()
            if self.tray_icon is not None:
                self.tray_icon.show()
                if not self._tray_message_shown:
                    self.tray_icon.showMessage(
                        APP_NAME,
                        "K-Sounds Hub is still running in the system tray.",
                        QSystemTrayIcon.Information,
                        1800,
                    )
                    self._tray_message_shown = True
            return

        self._meter_timer.stop()
        if self.tray_icon is not None:
            self.tray_icon.hide()
            try:
                self.tray_icon.deleteLater()
            except Exception:
                pass
            self.tray_icon = None
        self.ipc_server.stop()
        self.audio_engine.shutdown()
        event.accept()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
            QTimer.singleShot(150, app.quit)


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
                on_runtime_refresh=self._queue_runtime_view_refresh,
            )
            widget.changed.connect(self._on_any_changed)
            self.channel_widgets[channel.key] = widget
            self.columns_layout.addWidget(widget)

        self._apply_column_widths()

    def _autosave(self) -> None:
        self._normalize_app_rules()
        self.settings_store.save(self.settings)

    def _apply_channel_volume_fast(self, channel_key: str) -> None:
        fast_apply = getattr(self.audio_engine, "apply_channel_volume_fast", None)
        if callable(fast_apply):
            fast_apply(self.settings, channel_key)
            return
        self.audio_engine.apply_channel(self.settings, channel_key)

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

    def _queue_runtime_view_refresh(self, delay_ms: int = 20) -> None:
        remaining = self._runtime_view_timer.remainingTime()
        if remaining < 0 or remaining > delay_ms:
            self._runtime_view_timer.start(delay_ms)

    def _refresh_runtime_views_only(self) -> None:
        for widget in self.channel_widgets.values():
            widget.refresh_runtime_views()

    def _sync_runtime_audio_state(self) -> None:
        self.audio_engine.apply_settings(self.settings)
        self.refresh_status()

    def _on_any_changed(self) -> None:
        sender = self.sender()
        source_channel = getattr(sender, "channel", None)
        hint = getattr(sender, "_change_hint", "generic")

        if source_channel is None:
            self._link_shared_eq_library(source_channel=source_channel)
            self.audio_engine.apply_settings(self.settings)
            self._save_timer.start()
            self._status_timer.start()
            return

        # Hot path: while dragging a volume slider, keep the UI thread as light
        # as possible. No EQ library sync, no autosave reset, no overlay/status
        # refresh on every tick. The release event commits/saves afterwards.
        if hint == "volume_drag":
            self._apply_channel_volume_fast(source_channel.key)
            return

        # Volume, mute and slider commits do not need EQ library relinking.
        if hint not in {"volume", "volume_commit", "mute"}:
            self._link_shared_eq_library(source_channel=source_channel)

        if hint == "app_route":
            self._prefer_app_rules_for_channel(source_channel)
            self._normalize_app_rules()

        if hint == "volume_commit":
            self._apply_channel_volume_fast(source_channel.key)
            self._show_overlay_for_change(source_channel, "volume")
            self._save_timer.start()
            self._status_timer.start()
            return

        if hint == "volume":
            self._apply_channel_volume_fast(source_channel.key)
            self._show_overlay_for_change(source_channel, hint)
            self._save_timer.start()
            return

        if hint == "eq_preview":
            self._queue_channel_apply(source_channel.key, 95)
        elif hint == "app_route":
            self._queue_runtime_view_refresh(10)
            self._status_timer.start()
        elif hint == "mute":
            self.audio_engine.apply_channel(self.settings, source_channel.key)
            self._show_overlay_for_change(source_channel, hint)
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
        self.overlay.set_enabled(self.settings.overlay_enabled)
        self.backend_status.setText(
            self.audio_engine.status_text()
            + f" • channels: {enabled_channels}/{total_channels} • overlay: {overlay} • meter: {visualizer}"
        )
        for widget in self.channel_widgets.values():
            widget.set_global_visualizer_enabled(self.settings.visualizer_enabled)
            widget.refresh_runtime_views()

        # Meters are refreshed by the dedicated throttled meter timer.
        # Calling them again from refresh_status made the UI do duplicate work.

        if self.soundboard_dialog is not None and hasattr(self.soundboard_dialog, "refresh_route_controls"):
            self.soundboard_dialog.refresh_route_controls()
        self._apply_column_widths()

    def _refresh_meters(self) -> None:
        for widget in self.channel_widgets.values():
            if not self.settings.visualizer_enabled or not widget.channel.visualizer_enabled:
                widget.clear_meter_levels()
                continue
            left, right = self.audio_engine.meter_levels(widget.channel.key)
            widget.set_meter_levels(left, right)

    def _soundboard_route_state(self) -> dict[str, bool]:
        def linked(channel_key: str) -> bool:
            channel = self._find_channel(channel_key)
            if channel is None:
                return False
            return "soundboard" in {
                str(key).strip().lower()
                for key in getattr(channel, "linked_channels", []) or []
            }

        return {
            "monitor_to_mic_out": linked("return-mic"),
            "send_to_micro": linked("micro"),
        }

    def _set_soundboard_route_state(self, route_key: str, enabled: bool) -> bool:
        route_to_channel = {
            "monitor_to_mic_out": "return-mic",
            "send_to_micro": "micro",
        }

        channel_key = route_to_channel.get(str(route_key or "").strip())
        if not channel_key:
            return False

        channel = self._find_channel(channel_key)
        if channel is None:
            return False

        linked = [
            str(key).strip().lower()
            for key in getattr(channel, "linked_channels", []) or []
            if str(key).strip()
        ]

        before = list(linked)
        if enabled:
            if "soundboard" not in linked:
                linked.append("soundboard")
        else:
            linked = [key for key in linked if key != "soundboard"]

        channel.linked_channels = linked

        if linked != before:
            self.audio_engine.apply_channel(self.settings, channel_key)
            self.settings_store.save(self.settings)
            self._queue_runtime_view_refresh(10)
            self._status_timer.start()

        return True

    def _ensure_soundboard_dialog(self) -> SoundboardDialog:
        if self.soundboard_dialog is None:
            self.soundboard_dialog = SoundboardDialog(
                route_state_provider=self._soundboard_route_state,
                route_state_changed=self._set_soundboard_route_state,
            )
        return self.soundboard_dialog

    def open_soundboard(self) -> None:
        dialog = self._ensure_soundboard_dialog()
        if hasattr(dialog, "refresh_route_controls"):
            dialog.refresh_route_controls()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_settings(self) -> None:
        try:
            dialog = SettingsDialog(
                self.settings,
                self,
                wallpaper_preview_callback=self._preview_wallpaper_settings,
                wallpaper_reset_callback=self._restore_wallpaper_preview,
            )
        except TypeError:
            dialog = SettingsDialog(self.settings, self)

        if dialog.exec():
            self.settings = dialog.build_result()
            self._link_shared_eq_library()
            self._normalize_app_rules()
            self.overlay.set_enabled(self.settings.overlay_enabled)
            self._autosave()
            self._apply_wallpaper_settings()
            self._reload_channels()
            self.audio_engine.apply_settings(self.settings)
            self.refresh_status()
        else:
            self._restore_wallpaper_preview()
