from __future__ import annotations

"""
Experimental K-Sounds Hub Glass UI.

This module is intentionally separate from ksound_hub.app.
The stable app stays available as the fallback launcher.
Glass is being migrated into the real K-Sounds frontend.
Backend bindings are added gradually while the stable UI remains a fallback.
"""

import json
import math
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSlider,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


from .audio.pipewire_v2_final import PipeWireAudioEngine
from .config import CONFIG_DIR, IPC_SOCKET_PATH
from .control import resolve_ipc_socket_path
from .ipc import AudioIpcServer
from .settings_store import SettingsStore
from .ui.soundboard_dialog import SoundboardDialog

PACKAGE_ROOT = Path(__file__).resolve().parent
APP_ICON = PACKAGE_ROOT / "assets/app_icon.png"
APP_BG = PACKAGE_ROOT / "assets/backgrounds/ksound_hub_wallpaper_4k_blurfill_3840x2160.png"
SOUNDBOARD_PATH = CONFIG_DIR / "soundboard.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


def _send_ksh_ipc_payload(payload: dict) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(resolve_ipc_socket_path())
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except Exception:
        return False


def _read_saved_mixer_channel_state() -> dict[str, tuple[int, bool]]:
    if not SETTINGS_PATH.is_file():
        return {}

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    channels = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(channels, list):
        return {}

    state: dict[str, tuple[int, bool]] = {}
    for channel in channels:
        if not isinstance(channel, dict):
            continue

        key = str(channel.get("key") or "").strip()
        if not key:
            continue

        try:
            volume = max(0, min(100, int(channel.get("volume", 0))))
        except Exception:
            volume = 0

        state[key] = (volume, bool(channel.get("muted", False)))

    return state


GLASS_CHANNEL_KEY_ALIASES = {
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


class GlassBackendController(QObject):
    channel_state_changed = Signal(str, int, bool)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.audio_engine = PipeWireAudioEngine()

        self._pending_volume_fast_keys: set[str] = set()
        self._pending_apply_keys: set[str] = set()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self._autosave)

        self._volume_fast_timer = QTimer(self)
        self._volume_fast_timer.setSingleShot(True)
        self._volume_fast_timer.setInterval(45)
        self._volume_fast_timer.timeout.connect(self._flush_pending_volume_fast_apply)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(35)
        self._apply_timer.timeout.connect(self._flush_pending_channel_apply)

        self.ipc_server = AudioIpcServer(IPC_SOCKET_PATH, self)
        self.ipc_server.message_received.connect(self.handle_ipc_message)
        self.ipc_server.status_changed.connect(self.status_changed)
        self.ipc_server.start()

        # Apply backend after the UI has had a chance to appear.
        QTimer.singleShot(0, self.apply_startup_settings)

    def apply_startup_settings(self) -> None:
        try:
            self.audio_engine.apply_settings(self.settings)
            self.status_changed.emit(self.audio_engine.status_text())
        except Exception as exc:
            self.status_changed.emit(f"Audio backend startup error — {exc}")

    def shutdown(self) -> None:
        try:
            self._autosave()
        except Exception:
            pass
        try:
            self.ipc_server.stop()
        except Exception:
            pass
        try:
            self.audio_engine.shutdown()
        except Exception:
            pass

    def _normalize_channel_key(self, value: str) -> str:
        raw = str(value or "").strip().lower().replace(" ", "-")
        return GLASS_CHANNEL_KEY_ALIASES.get(raw, raw)

    def _find_channel(self, channel_key: str):
        key = self._normalize_channel_key(channel_key)
        for channel in self.settings.channels:
            if channel.key == key:
                return channel
        return None

    def channel_state(self, channel_key: str) -> tuple[int, bool] | None:
        channel = self._find_channel(channel_key)
        if channel is None:
            return None
        return int(channel.volume), bool(channel.muted)

    def set_channel_volume(self, channel_key: str, value: int) -> bool:
        return self._apply_mixer_action(channel_key, "set-volume", volume=value)

    def set_channel_muted(self, channel_key: str, muted: bool) -> bool:
        return self._apply_mixer_action(channel_key, "set-mute", muted=muted)

    def handle_ipc_message(self, payload: dict) -> None:
        channel_key = self._normalize_channel_key(payload.get("channel", ""))
        action = str(payload.get("action", "")).strip().lower()
        if not channel_key or not action:
            return

        self._apply_mixer_action(
            channel_key,
            action,
            volume=payload.get("volume"),
            muted=payload.get("muted", payload.get("checked", None)),
        )

    def _apply_mixer_action(self, channel_key: str, action: str, *, volume=None, muted=None) -> bool:
        channel = self._find_channel(channel_key)
        if channel is None:
            return False

        action = str(action or "").strip().lower()
        hint = "generic"
        changed = False

        if action in {"set-mute", "set_mute"}:
            if isinstance(muted, str):
                channel.muted = muted.strip().lower() in {"1", "true", "yes", "on", "muted"}
            else:
                channel.muted = bool(muted)
            hint = "mute"
            changed = True

        elif action in {"volup", "voldown", "set-volume"} and channel.muted:
            # Keep the stable app behavior: volume shortcuts do not move muted channels.
            self.channel_state_changed.emit(channel.key, int(channel.volume), bool(channel.muted))
            return True

        elif action == "volup":
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
                channel.volume = max(0, min(100, int(volume)))
            except Exception:
                return False
            hint = "volume"
            changed = True

        if not changed:
            return False

        # UI first: shortcuts feel instant, audio apply is coalesced right after.
        self.channel_state_changed.emit(channel.key, int(channel.volume), bool(channel.muted))

        if hint == "volume":
            self._pending_volume_fast_keys.add(channel.key)
            if not self._volume_fast_timer.isActive():
                self._volume_fast_timer.start()
        else:
            self._pending_apply_keys.add(channel.key)
            if not self._apply_timer.isActive():
                self._apply_timer.start()

        self._save_timer.start()
        return True

    def _flush_pending_volume_fast_apply(self) -> None:
        keys = set(self._pending_volume_fast_keys)
        self._pending_volume_fast_keys.clear()

        fast_apply = getattr(self.audio_engine, "apply_channel_volume_fast", None)
        for key in keys:
            try:
                if callable(fast_apply):
                    fast_apply(self.settings, key)
                else:
                    self.audio_engine.apply_channel(self.settings, key)
            except Exception as exc:
                self.status_changed.emit(f"Volume apply error on {key} — {exc}")

    def _flush_pending_channel_apply(self) -> None:
        keys = set(self._pending_apply_keys)
        self._pending_apply_keys.clear()

        for key in keys:
            try:
                self.audio_engine.apply_channel(self.settings, key)
            except Exception as exc:
                self.status_changed.emit(f"Channel apply error on {key} — {exc}")

    def _autosave(self) -> None:
        try:
            self.settings_store.save(self.settings)
        except Exception as exc:
            self.status_changed.emit(f"Settings save error — {exc}")


CHANNELS = [
    ("ALL", "A", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 76, "all"),
    ("GAME", "G", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 72, "game"),
    ("MEDIA", "M", ["USB / SPDIF", "Arctis Nova Pro", "System default"], 64, "media"),
    ("CHAT", "C", ["Arctis Nova Pro", "USB / SPDIF", "System default"], 70, "chat"),
    ("MORE", "+", ["System default", "Arctis Nova Pro", "USB / SPDIF"], 58, "more"),
    ("MICRO", "µ", ["RØDE NT-USB", "Arctis Mic", "System default"], 84, "micro"),
    ("MIC OUT", "R", ["Arctis monitor", "USB / SPDIF", "System default"], 52, "return-mic"),
]


STYLE = """
QWidget {
    color: #edf5ff;
    background: transparent;
    font-family: "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
}

QMainWindow {
    background: #02050a;
}

QWidget#root,
QWidget#foreground {
    background: transparent;
}

QLabel#backgroundImage {
    background: #02050a;
}

QFrame#backgroundTint {
    background: rgba(0, 0, 0, 130);
    border: none;
}

QFrame#backgroundWash {
    background: rgba(90, 130, 255, 24);
    border: none;
}

QFrame#titleBar {
    background: rgba(0, 0, 0, 126);
    border: none;
}

QFrame#contentFrame {
    background: rgba(0, 0, 0, 52);
    border: none;
}

QFrame#navRail,
QFrame#channelCard,
QFrame#drawer {
    background: rgba(0, 0, 0, 178);
    border: none;
    border-radius: 15px;
}

QFrame#channelCard:hover {
    background: rgba(5, 13, 22, 194);
    border: none;
}

QFrame#channelCard[muted="true"] {
    background: rgba(82, 18, 24, 190);
    border: none;
}

QFrame#channelCard[muted="true"]:hover {
    background: rgba(104, 22, 31, 205);
    border: none;
}

QPushButton#windowButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 6px;
    background: transparent;
    border: none;
    color: rgba(226, 242, 255, 190);
}

QPushButton#windowButton:hover {
    background: rgba(30, 56, 84, 150);
    border: none;
}

QPushButton#closeButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 6px;
    background: transparent;
    border: none;
    color: rgba(255, 220, 228, 205);
}

QPushButton#closeButton:hover {
    background: rgba(190, 38, 58, 170);
    border: none;
}

QPushButton#navButton {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 7px 2px;
    color: rgba(218, 236, 250, 170);
    font-size: 10px;
}

QPushButton#navButton:checked {
    background: rgba(20, 106, 176, 82);
    border: none;
    color: #f2fbff;
}

QPushButton#navButton:hover {
    background: rgba(18, 40, 62, 115);
    border: none;
}

QLabel#appIcon {
    min-width: 22px;
    min-height: 22px;
    max-width: 22px;
    max-height: 22px;
    border-radius: 0px;
    background: transparent;
    border: none;
    color: #dff7ff;
    font-size: 12px;
    font-weight: 900;
}

QLabel#titleText {
    color: rgba(222, 238, 250, 190);
    font-size: 11px;
    font-weight: 700;
}

QLabel#muted {
    color: rgba(205, 224, 242, 150);
    font-size: 10px;
}

QLabel#channelIcon {
    min-width: 38px;
    min-height: 38px;
    max-width: 38px;
    max-height: 38px;
    border-radius: 0px;
    border: none;
    background: transparent;
    color: #86dcff;
    font-size: 21px;
    font-weight: 900;
}

QLabel#channelName {
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 1.7px;
}

QLabel#volumeValue {
    color: rgba(225, 242, 255, 212);
    font-size: 11px;
    font-weight: 850;
}

QLabel#sectionTitle {
    color: #e8f5ff;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 1.2px;
}

QPushButton {
    background: rgba(8, 17, 28, 128);
    border: none;
    border-radius: 10px;
    padding: 5px 9px;
}

QPushButton:hover {
    background: rgba(14, 32, 50, 150);
    border: none;
}

QPushButton#muteButton {
    padding: 5px 5px;
    font-size: 10px;
}

QPushButton#muteButton:checked {
    background: rgba(160, 42, 52, 170);
    color: #ffecef;
    border: none;
}

QPushButton#primaryButton {
    background: rgba(35, 142, 226, 112);
    border: none;
}

QPushButton#demoButton {
    background: rgba(35, 142, 226, 105);
    border: none;
    border-radius: 10px;
    padding: 7px 10px;
    font-weight: 750;
}

QPushButton#toggleSwitch {
    min-width: 54px;
    max-width: 54px;
    min-height: 25px;
    max-height: 25px;
    border-radius: 13px;
    padding: 0px;
    background: rgba(25, 35, 48, 180);
    border: none;
    color: rgba(210, 225, 240, 180);
    font-size: 10px;
    font-weight: 800;
}

QPushButton#toggleSwitch:checked {
    background: rgba(45, 165, 240, 175);
    color: #f2fbff;
}

QFrame#padsTopBar {
    background: rgba(0, 0, 0, 80);
    border: none;
    border-radius: 12px;
}

QPushButton#padTopButton {
    background: rgba(20, 38, 55, 145);
    border: none;
    border-radius: 10px;
    padding: 7px 9px;
    font-weight: 760;
}

QPushButton#padTopButton:hover {
    background: rgba(35, 80, 115, 155);
    border: none;
}

QPushButton#padTopButton:checked {
    background: rgba(45, 150, 225, 160);
    border: none;
}

QPushButton#padAddButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 30px;
    max-height: 30px;
    background: rgba(55, 165, 238, 150);
    border: none;
    border-radius: 15px;
    padding: 0px;
    font-size: 17px;
    font-weight: 900;
}

QFrame#soundPadCard {
    background: rgba(0, 0, 0, 150);
    border: none;
    border-radius: 14px;
}

QFrame#soundPadCard:hover {
    background: rgba(8, 24, 38, 176);
    border: none;
}

QFrame#soundPadCard[edit="true"] {
    background: rgba(11, 31, 47, 188);
    border: none;
}

QLabel#soundPadIcon {
    min-width: 34px;
    min-height: 30px;
    max-height: 30px;
    background: transparent;
    border: none;
    font-size: 22px;
}

QLabel#soundPadName {
    color: rgba(240, 248, 255, 225);
    font-size: 11px;
    font-weight: 780;
}

QLabel#soundPadMeta {
    color: rgba(205, 224, 242, 140);
    font-size: 9px;
}

QFrame#soundPadActions {
    background: rgba(0, 0, 0, 90);
    border: none;
    border-radius: 10px;
}

QPushButton#padIconButton {
    min-width: 26px;
    max-width: 26px;
    min-height: 24px;
    max-height: 24px;
    background: rgba(25, 48, 70, 150);
    border: none;
    border-radius: 8px;
    padding: 0px;
    font-size: 12px;
}

QPushButton#padIconButton:hover {
    background: rgba(45, 108, 152, 170);
    border: none;
}

QPushButton#padDeleteButton {
    min-width: 26px;
    max-width: 26px;
    min-height: 24px;
    max-height: 24px;
    background: rgba(120, 28, 38, 155);
    border: none;
    border-radius: 8px;
    padding: 0px;
    font-size: 12px;
}

QPushButton#padDeleteButton:hover {
    background: rgba(170, 42, 55, 185);
    border: none;
}


QFrame#soundPadCard {
    background: rgba(0, 0, 0, 150);
    border: none;
    border-radius: 12px;
}

QFrame#soundPadCard:hover {
    background: rgba(8, 24, 38, 176);
    border: none;
}

QFrame#soundPadCard[edit="true"] {
    background: rgba(11, 31, 47, 188);
    border: none;
}

QLabel#soundPadIcon {
    min-width: 30px;
    min-height: 24px;
    max-height: 24px;
    background: transparent;
    border: none;
    font-size: 20px;
}

QLabel#soundPadName {
    color: rgba(240, 248, 255, 225);
    font-size: 10px;
    font-weight: 780;
}

QLabel#soundPadMeta {
    color: rgba(205, 224, 242, 140);
    font-size: 8px;
}

QFrame#appsRouteCard {
    background: rgba(0, 0, 0, 138);
    border: none;
    border-radius: 13px;
}

QFrame#appsRouteCard:hover {
    background: rgba(8, 24, 38, 176);
    border: none;
}

QLabel#appRouteIcon {
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    background: rgba(40, 115, 175, 80);
    border: none;
    border-radius: 15px;
    font-size: 15px;
}

QLabel#appRouteName {
    font-size: 11px;
    font-weight: 820;
}

QLabel#appRouteMeta {
    color: rgba(205, 224, 242, 145);
    font-size: 9px;
}

QLabel#appRouteArrow {
    color: rgba(135, 210, 255, 190);
    font-size: 16px;
    font-weight: 900;
}

QPushButton#soundPadEmoji {
    min-width: 32px;
    max-width: 32px;
    min-height: 28px;
    max-height: 28px;
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0px;
    font-size: 20px;
}

QPushButton#soundPadEmoji:hover {
    background: rgba(40, 80, 110, 95);
    border: none;
}

QLineEdit#soundPadNameEditor {
    background: rgba(0, 0, 0, 130);
    border: none;
    border-radius: 8px;
    color: rgba(240, 248, 255, 235);
    font-size: 10px;
    font-weight: 780;
    padding: 3px 5px;
}

QFrame#emojiPalette {
    background: rgba(0, 0, 0, 150);
    border: none;
    border-radius: 10px;
}

QPushButton#emojiChoice {
    min-width: 24px;
    max-width: 24px;
    min-height: 22px;
    max-height: 22px;
    background: rgba(20, 38, 55, 105);
    border: none;
    border-radius: 7px;
    padding: 0px;
    font-size: 15px;
}

QPushButton#emojiChoice:hover {
    background: rgba(45, 108, 152, 160);
    border: none;
}

QComboBox {
    background: rgba(0, 0, 0, 132);
    border: none;
    border-radius: 9px;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 10px;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QSlider::groove:vertical {
    background: rgba(0, 0, 0, 150);
    width: 6px;
    border: none;
    border-radius: 3px;
}

QSlider::handle:vertical {
    background: rgba(108, 211, 255, 240);
    border: none;
    width: 16px;
    height: 12px;
    margin: 0px -5px;
    border-radius: 6px;
}

QSlider::sub-page:vertical {
    background: rgba(0, 0, 0, 180);
    border-radius: 4px;
}

QSlider::add-page:vertical {
    background: rgba(76, 188, 255, 128);
    border-radius: 4px;
}

QSlider::groove:horizontal {
    background: rgba(0, 0, 0, 145);
    height: 6px;
    border: none;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: rgba(108, 211, 255, 240);
    border: none;
    width: 18px;
    height: 18px;
    margin: -6px 0px;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background: rgba(82, 190, 255, 120);
    border-radius: 5px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea#drawerScroll {
    border: none;
    background: transparent;
}

QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
    width: 6px;
    height: 6px;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: rgba(92, 204, 255, 70);
    border-radius: 3px;
}


QPushButton#selectButton {
    background: rgba(0, 0, 0, 132);
    border: none;
    border-radius: 9px;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 10px;
    text-align: center;
}

QPushButton#selectButton:hover {
    background: rgba(14, 32, 50, 150);
    border: none;
}

QMenu {
    background: rgba(0, 0, 0, 220);
    color: #edf5ff;
    border: none;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    background: transparent;
    padding: 6px 20px;
    border-radius: 7px;
}

QMenu::item:selected {
    background: rgba(45, 150, 225, 155);
}

QFrame#emojiPalette {
    background: rgba(0, 0, 0, 205);
    border: none;
    border-radius: 14px;
}


QPushButton#padStopAllButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 30px;
    max-height: 30px;
    padding: 0px;
    border-radius: 10px;
    border: 1px solid rgba(255, 125, 135, 130);
    background: rgba(205, 38, 58, 180);
    color: rgba(255, 238, 241, 245);
    font-size: 14px;
    font-weight: 950;
}

QPushButton#padStopAllButton:hover {
    background: rgba(235, 56, 78, 215);
    border: 1px solid rgba(255, 168, 176, 180);
}

QPushButton#padStopAllButton:pressed {
    background: rgba(255, 76, 98, 235);
    border: 1px solid rgba(255, 205, 212, 220);
}

QPushButton#padStopAllButton:disabled {
    background: rgba(118, 30, 42, 135);
    color: rgba(255, 226, 231, 130);
    border: 1px solid rgba(255, 125, 135, 70);
}

QPushButton#padBulkDeleteButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 30px;
    max-height: 30px;
    background: rgba(150, 32, 46, 170);
    border: none;
    border-radius: 15px;
    padding: 0px;
    font-size: 15px;
    font-weight: 900;
}

QPushButton#padBulkDeleteButton:checked {
    background: rgba(35, 165, 92, 175);
    border: none;
}

QPushButton#padCancelButton {
    min-width: 48px;
    min-height: 30px;
    background: rgba(42, 58, 72, 155);
    border: none;
    border-radius: 10px;
    padding: 0px 9px;
    font-size: 10px;
    font-weight: 760;
}

QFrame#soundPadCard[bulkSelected="true"] {
    background: rgba(40, 130, 92, 205);
    border: none;
}

QFrame#soundPadCard[bulkSelected="true"]:hover {
    background: rgba(48, 152, 108, 220);
    border: none;
}

QScrollArea#drawerScroll {
    border: none;
    background: transparent;
    padding-right: 10px;
}

QScrollBar:vertical {
    background: rgba(0, 0, 0, 35);
    width: 8px;
    margin: 0px 0px 0px 4px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(92, 204, 255, 80);
    border-radius: 4px;
    min-height: 28px;
}


/* V16 overrides */
QFrame#soundPadCard[bulkSelected="true"] {
    background: rgba(150, 32, 46, 215);
    border: none;
}

QFrame#soundPadCard[bulkSelected="true"]:hover {
    background: rgba(180, 42, 58, 230);
    border: none;
}

QScrollArea#drawerScroll {
    border: none;
    background: transparent;
    padding-right: 0px;
}

QScrollBar:vertical {
    background: rgba(0, 0, 0, 28);
    width: 7px;
    margin: 0px 0px 0px 3px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(92, 204, 255, 75);
    border-radius: 4px;
    min-height: 28px;
}


/* V17 scrollbar spacing override */
QScrollArea#drawerScroll {
    border: none;
    background: transparent;
    padding-right: 0px;
}

QScrollBar:vertical {
    background: rgba(0, 0, 0, 24);
    width: 7px;
    margin: 0px 1px 0px 6px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(92, 204, 255, 75);
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}


/* V18 pad compact action buttons */
QPushButton#padIconButton,
QPushButton#padDeleteButton {
    min-width: 22px;
    max-width: 22px;
    min-height: 20px;
    max-height: 20px;
    border: none;
    border-radius: 7px;
    padding: 0px;
    font-size: 10px;
}

QFrame#soundPadActions {
    background: rgba(0, 0, 0, 70);
    border: none;
    border-radius: 9px;
}


/* V20 detached soundboard background controls */
QFrame#detachedBgControls {
    background: rgba(0, 0, 0, 112);
    border: none;
    border-radius: 14px;
}

QLabel#detachedBgTitle {
    color: rgba(235, 247, 255, 220);
    font-size: 12px;
    font-weight: 850;
    letter-spacing: 0.8px;
}

QLabel#detachedBgLabel {
    color: rgba(215, 232, 246, 170);
    font-size: 10px;
}


/* Glass real soundboard pad text clamp */
QLabel#soundPadName {
    min-height: 17px;
    max-height: 17px;
}

QLabel#soundPadMeta {
    min-height: 13px;
    max-height: 13px;
}


/* Glass final pads polish */
QPushButton#padAddButton,
QPushButton#padBulkDeleteButton {
    qproperty-iconSize: 0px 0px;
    padding: 0px;
    text-align: center;
}

QPushButton#padDeleteButton {
    qproperty-iconSize: 0px 0px;
    padding: 0px;
    text-align: center;
}

QScrollArea#padsGridScroll {
    border: none;
    background: transparent;
    padding-right: 0px;
}


/* Glass pads internal scrollbar */
QScrollBar#padsGridScrollbar:vertical {
    background: rgba(0, 0, 0, 95);
    width: 8px;
    margin: 4px 1px 4px 3px;
    border: none;
    border-radius: 4px;
}

QScrollBar#padsGridScrollbar::handle:vertical {
    background: rgba(92, 204, 255, 170);
    border: none;
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar#padsGridScrollbar::handle:vertical:hover {
    background: rgba(115, 220, 255, 215);
}

QScrollBar#padsGridScrollbar::add-line:vertical,
QScrollBar#padsGridScrollbar::sub-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}

QScrollBar#padsGridScrollbar::add-page:vertical,
QScrollBar#padsGridScrollbar::sub-page:vertical {
    background: transparent;
    border: none;
}
"""





class AdaptiveScrollArea(QScrollArea):
    RIGHT_MARGIN_WITH_SCROLL = 10

    def __init__(self):
        super().__init__()
        self.setObjectName("drawerScroll")
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._applied_right_margin = -1
        self._pending_margin_update = False

        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(lambda _minimum, _maximum: self._schedule_margin_update())
        bar.valueChanged.connect(lambda _value: self._schedule_margin_update())

    def setWidget(self, widget) -> None:
        super().setWidget(widget)
        self._schedule_margin_update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_margin_update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_margin_update()

    def _schedule_margin_update(self) -> None:
        if self._pending_margin_update:
            return

        self._pending_margin_update = True
        QTimer.singleShot(0, self._update_scroll_margin)
        QTimer.singleShot(80, self._update_scroll_margin)

    def _update_scroll_margin(self) -> None:
        self._pending_margin_update = False

        bar = self.verticalScrollBar()
        has_scroll = bar.maximum() > bar.minimum()
        right_margin = self.RIGHT_MARGIN_WITH_SCROLL if has_scroll else 0

        if right_margin == self._applied_right_margin:
            return

        self._applied_right_margin = right_margin
        self.setViewportMargins(0, 0, right_margin, 0)

        widget = self.widget()
        if widget is not None:
            widget.updateGeometry()
            widget.adjustSize()

class NoWheelComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setAlignment(Qt.AlignCenter)
        self.lineEdit().setFrame(False)
        self.currentIndexChanged.connect(lambda _idx: self._sync_display_text())

    def wheelEvent(self, event) -> None:
        event.ignore()

    def addItems(self, texts) -> None:
        super().addItems(texts)
        self._sync_display_text()

    def setCurrentIndex(self, index: int) -> None:
        super().setCurrentIndex(index)
        self._sync_display_text()

    def setCurrentText(self, text: str) -> None:
        index = self.findText(text)
        if index >= 0:
            super().setCurrentIndex(index)
        else:
            super().setCurrentText(text)
        self._sync_display_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_display_text()

    def showPopup(self) -> None:
        current = self._full_current_text()
        if self.lineEdit() is not None:
            self.lineEdit().setText(current)
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._sync_display_text()

    def _full_current_text(self) -> str:
        if self.currentIndex() >= 0:
            return self.itemText(self.currentIndex())
        return super().currentText()

    def _sync_display_text(self) -> None:
        line = self.lineEdit()
        if line is None:
            return
        full = self._full_current_text()
        width = max(24, line.width() - 8)
        elided = line.fontMetrics().elidedText(full, Qt.ElideRight, width)
        line.blockSignals(True)
        line.setText(elided)
        line.setCursorPosition(0)
        line.blockSignals(False)
        self.setToolTip(full)



class NoWheelSlider(QSlider):
    def wheelEvent(self, event) -> None:
        event.ignore()





class SelectButton(QPushButton):
    def __init__(self, items: list[str], current: str | None = None, on_change=None, parent=None):
        super().__init__(parent)
        self.setObjectName("selectButton")
        self.items = list(items)
        self._current = current if current is not None else (self.items[0] if self.items else "")
        self._on_change = on_change
        self.clicked.connect(self._open_menu)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._sync_text()

    def current_text(self) -> str:
        return self._current

    def set_current_text(self, value: str) -> None:
        if value not in self.items and self.items:
            value = self.items[0]
        changed = value != self._current
        self._current = value
        self._sync_text()
        if changed and self._on_change is not None:
            self._on_change(value)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_text()

    def _sync_text(self) -> None:
        width = max(28, self.width() - 16)
        text = self.fontMetrics().elidedText(self._current, Qt.ElideRight, width)
        self.setText(text)
        self.setToolTip(self._current)

    def _open_menu(self) -> None:
        if not self.items:
            return
        menu = QMenu(self)
        menu.setFixedWidth(max(1, self.width()))
        for item in self.items:
            action = menu.addAction(item)
            action.triggered.connect(lambda _checked=False, value=item: self.set_current_text(value))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

class LevelMeter(QWidget):
    def __init__(self, level: float = 0.0, parent=None):
        super().__init__(parent)
        self.current = max(0.0, min(1.0, float(level)))
        self.target = self.current
        self.peak = self.current
        self.setFixedWidth(10)
        self.setMinimumHeight(124)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def set_level(self, level: float) -> None:
        self.target = max(0.0, min(1.0, float(level)))
        if self.target > self.peak:
            self.peak = self.target

    def tick(self) -> None:
        if self.target > self.current:
            self.current = self.current * 0.32 + self.target * 0.68
        else:
            self.current = self.current * 0.88 + self.target * 0.12
        self.peak = max(self.current, self.peak * 0.965)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        segments = 20
        gap = 2.0
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        segment_h = max(2.0, (rect.height() - gap * (segments - 1)) / segments)
        active = int(round(self.current * segments))
        peak_index = max(0, min(segments - 1, int(round(self.peak * segments)) - 1))

        for i in range(segments):
            y = rect.bottom() - (i + 1) * segment_h - i * gap
            seg = QRectF(rect.left(), y, rect.width(), segment_h)

            if i < active:
                if i >= int(segments * 0.84):
                    color = QColor(255, 178, 70, 205)
                elif i >= int(segments * 0.68):
                    color = QColor(90, 235, 145, 190)
                else:
                    color = QColor(70, 210, 255, 165)
            else:
                color = QColor(10, 22, 34, 118)

            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(seg, 1.8, 1.8)

        peak_y = rect.bottom() - (peak_index + 1) * segment_h - peak_index * gap
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(225, 250, 255, 220))
        painter.drawRoundedRect(QRectF(rect.left() - 1.0, peak_y, rect.width() + 2.0, 2.0), 1.0, 1.0)


class TitleBar(QFrame):
    def __init__(self, window: QMainWindow):
        super().__init__()
        self.window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        icon = QLabel("K")
        icon.setObjectName("appIcon")
        icon.setAlignment(Qt.AlignCenter)
        if APP_ICON.is_file():
            pixmap = QPixmap(str(APP_ICON))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(icon)

        title = QLabel("K-Sounds Hub Glass")
        title.setObjectName("titleText")
        layout.addWidget(title)

        layout.addStretch(1)

        min_btn = QPushButton("—")
        min_btn.setObjectName("windowButton")
        min_btn.clicked.connect(window.showMinimized)
        layout.addWidget(min_btn)

        max_btn = QPushButton("□")
        max_btn.setObjectName("windowButton")
        max_btn.clicked.connect(self._toggle_maximized)
        layout.addWidget(max_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn)

    def _toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle = self.window.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            event.accept()


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str):
        super().__init__(f"{icon}\n{label}")
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setMinimumHeight(58)




class ChannelCard(QFrame):
    def __init__(
        self,
        name: str,
        icon: str,
        devices: list[str],
        value: int,
        channel_key: str = "",
        volume_callback=None,
        mute_callback=None,
    ):
        super().__init__()
        self.channel_key = str(channel_key or "").strip()
        self._volume_callback = volume_callback
        self._mute_callback = mute_callback
        self._syncing_controls = False
        self.value = int(value)
        self.setObjectName("channelCard")
        self.setProperty("muted", "false")
        self.setMinimumWidth(78)
        self.setMaximumWidth(168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label, 0, Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        device_combo = SelectButton(devices, devices[0])
        device_combo.setMinimumWidth(0)
        device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(device_combo)

        meter_row = QHBoxLayout()
        meter_row.setContentsMargins(0, 2, 0, 2)
        meter_row.setSpacing(18)
        meter_row.addStretch(1)

        self.left_meter = LevelMeter(0.0)
        self.right_meter = LevelMeter(0.0)
        meter_row.addWidget(self.left_meter)

        self.slider = NoWheelSlider(Qt.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(value)
        self.slider.setMinimumHeight(124)
        self.slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.slider.setTracking(False)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.valueChanged.connect(self._on_volume_changed)
        meter_row.addWidget(self.slider, 0, Qt.AlignHCenter)

        meter_row.addWidget(self.right_meter)
        meter_row.addStretch(1)
        root.addLayout(meter_row, 1)

        self.value_label = QLabel(f"{value}%")
        self.value_label.setObjectName("volumeValue")
        self.value_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.value_label)

        self.mute_btn = QPushButton("Mute")
        self.mute_btn.setObjectName("muteButton")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._on_muted_changed)
        root.addWidget(self.mute_btn)

    def _set_volume_label(self, value: int) -> None:
        self.value = max(0, min(100, int(value)))
        self.value_label.setText(f"{self.value}%")

    def _on_slider_moved(self, value: int) -> None:
        self._set_volume_label(value)

    def _on_volume_changed(self, value: int) -> None:
        self._set_volume_label(value)
        if self._syncing_controls or self._volume_callback is None or not self.channel_key:
            return
        ok = bool(self._volume_callback(self.channel_key, self.value))
        if not ok:
            self.setToolTip("K-Sounds real app IPC is not reachable.")

    def _apply_muted_style(self, checked: bool) -> None:
        self.setProperty("muted", "true" if checked else "false")
        self.mute_btn.setText("Muted" if checked else "Mute")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _on_muted_changed(self, checked: bool) -> None:
        self._apply_muted_style(bool(checked))
        if self._syncing_controls or self._mute_callback is None or not self.channel_key:
            return
        ok = bool(self._mute_callback(self.channel_key, bool(checked)))
        if not ok:
            self.setToolTip("K-Sounds real app IPC is not reachable.")

    def sync_from_saved_state(self, *, volume: int | None = None, muted: bool | None = None) -> None:
        self._syncing_controls = True
        try:
            if volume is not None:
                value = max(0, min(100, int(volume)))
                self.slider.blockSignals(True)
                self.slider.setValue(value)
                self.slider.blockSignals(False)
                self._set_volume_label(value)

            if muted is not None:
                checked = bool(muted)
                self.mute_btn.blockSignals(True)
                self.mute_btn.setChecked(checked)
                self.mute_btn.blockSignals(False)
                self._apply_muted_style(checked)
        finally:
            self._syncing_controls = False

    def set_meter_levels(self, left: float, right: float) -> None:
        self.left_meter.set_level(left)
        self.right_meter.set_level(right)

    def tick_meters(self) -> None:
        self.left_meter.tick()
        self.right_meter.tick()





class AppRouteCard(QFrame):
    CHANNELS = ["ALL", "GAME", "MEDIA", "CHAT", "MORE", "MICRO", "MIC OUT"]

    def __init__(self, icon: str, name: str, meta: str, target: str):
        super().__init__()
        self.setObjectName("appsRouteCard")
        self.setMinimumHeight(58)
        self.meta = meta

        root = QHBoxLayout(self)
        root.setContentsMargins(9, 7, 9, 7)
        root.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("appRouteIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name_label = QLabel(name)
        name_label.setObjectName("appRouteName")
        text_col.addWidget(name_label)

        self.meta_label = QLabel(f"{meta} → {target}")
        self.meta_label.setObjectName("appRouteMeta")
        text_col.addWidget(self.meta_label)

        root.addLayout(text_col, 1)

        arrow = QLabel("→")
        arrow.setObjectName("appRouteArrow")
        arrow.setAlignment(Qt.AlignCenter)
        root.addWidget(arrow)

        select = SelectButton(self.CHANNELS, target, self._channel_changed)
        select.setMinimumWidth(100)
        select.setMaximumWidth(122)
        root.addWidget(select)

    def _channel_changed(self, channel: str) -> None:
        self.meta_label.setText(f"{self.meta} → {channel}")

class AppsPanel(QWidget):
    SAMPLE_APPS = [
        ("🎮", "Steam Game", "Game audio stream", "GAME"),
        ("🌐", "Firefox", "Browser media", "MEDIA"),
        ("💬", "Discord", "Voice chat", "CHAT"),
        ("🎵", "Spotify", "Music", "MEDIA"),
        ("🎙", "RØDE Monitor", "Mic monitoring", "MIC OUT"),
        ("🧪", "Unknown app", "New source", "MORE"),
    ]

    def __init__(self):
        super().__init__()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        hint = QLabel("Move app/source streams to channels")
        hint.setObjectName("muted")
        root.addWidget(hint)

        for icon, name, meta, target in self.SAMPLE_APPS:
            root.addWidget(AppRouteCard(icon, name, meta, target))

        root.addStretch(1)








class CenterGlyphButton(QPushButton):
    def __init__(self, glyph: str, parent=None, y_offset: int = 0):
        super().__init__("", parent)
        self._glyph = glyph
        self._y_offset = int(y_offset)
        self.setMinimumWidth(0)

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        if not self._glyph:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))

        metrics = painter.fontMetrics()
        bounds = metrics.tightBoundingRect(self._glyph)
        if bounds.isNull():
            bounds = metrics.boundingRect(self._glyph)

        x = (self.width() - bounds.width()) / 2.0 - bounds.left()
        y = (self.height() - bounds.height()) / 2.0 - bounds.top() + self._y_offset

        painter.drawText(int(round(x)), int(round(y)), self._glyph)

class HoverScrollLabel(QLabel):
    SCROLL_GAP = 34
    SCROLL_STEP = 2

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._offset = 0
        self._scrolling = False

        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._tick_scroll)

        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = str(text or "")
        self._offset = 0
        self.setToolTip(self._full_text)
        self.update()

    def text(self) -> str:
        return self._full_text

    def _needs_scroll(self) -> bool:
        width = max(8, self.contentsRect().width() - 2)
        return self.fontMetrics().horizontalAdvance(self._full_text) > width

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._scrolling = self._needs_scroll()
        self._offset = 0
        if self._scrolling:
            self._timer.start()
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._timer.stop()
        self._scrolling = False
        self._offset = 0
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._scrolling and not self._needs_scroll():
            self._timer.stop()
            self._scrolling = False
            self._offset = 0
        self.update()

    def _tick_scroll(self) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self._full_text)
        limit = max(1, text_width + self.SCROLL_GAP)
        self._offset = (self._offset + self.SCROLL_STEP) % limit
        self.update()

    def paintEvent(self, event) -> None:
        if not self._full_text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))

        rect = self.contentsRect()
        metrics = self.fontMetrics()

        if not self._scrolling or not self._needs_scroll():
            width = max(8, rect.width() - 2)
            elided = metrics.elidedText(self._full_text, Qt.ElideRight, width)
            painter.drawText(rect, self.alignment() | Qt.TextSingleLine, elided)
            return

        text_width = metrics.horizontalAdvance(self._full_text)
        baseline = rect.y() + (rect.height() + metrics.ascent() - metrics.descent()) // 2
        x = rect.x() - self._offset

        painter.drawText(x, baseline, self._full_text)
        painter.drawText(x + text_width + self.SCROLL_GAP, baseline, self._full_text)

class SoundPadCard(QFrame):
    def __init__(
        self,
        name: str,
        icon: str,
        meta: str,
        emoji_callback=None,
        delete_callback=None,
        play_callback=None,
        slot_key: str = "",
    ):
        super().__init__()
        self._edit_enabled = False
        self._bulk_select_enabled = False
        self._bulk_selected = False
        self._emoji_callback = emoji_callback
        self._delete_callback = delete_callback
        self._play_callback = play_callback
        self._slot_key = str(slot_key or "").strip()

        self.setObjectName("soundPadCard")
        self.setProperty("edit", "false")
        self.setProperty("bulkSelected", "false")
        self.setMinimumHeight(70)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(5, 5, 5, 5)
        root.setSpacing(3)

        self.icon_button = QPushButton(icon)
        self.icon_button.setObjectName("soundPadEmoji")
        self.icon_button.clicked.connect(self._request_emoji_palette)
        root.addWidget(self.icon_button, 0, Qt.AlignHCenter)

        self.name_label = HoverScrollLabel(name)
        self.name_label.setObjectName("soundPadName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFixedHeight(17)
        self.name_label.mouseDoubleClickEvent = self._start_rename
        root.addWidget(self.name_label)

        self.name_editor = QLineEdit(name)
        self.name_editor.setObjectName("soundPadNameEditor")
        self.name_editor.setAlignment(Qt.AlignCenter)
        self.name_editor.setVisible(False)
        self.name_editor.editingFinished.connect(self._finish_rename)
        root.addWidget(self.name_editor)

        meta_label = HoverScrollLabel(meta)
        meta_label.setObjectName("soundPadMeta")
        meta_label.setAlignment(Qt.AlignCenter)
        meta_label.setFixedHeight(13)
        root.addWidget(meta_label)

        self.actions = QFrame()
        self.actions.setObjectName("soundPadActions")
        actions_layout = QHBoxLayout(self.actions)
        actions_layout.setContentsMargins(3, 2, 3, 2)
        actions_layout.setSpacing(3)
        actions_layout.addStretch(1)

        bg_button = QPushButton("🖼")
        bg_button.setObjectName("padIconButton")
        bg_button.setToolTip("Edit background")
        actions_layout.addWidget(bg_button)

        sound_button = QPushButton("🎵")
        sound_button.setObjectName("padIconButton")
        sound_button.setToolTip("Edit sound")
        actions_layout.addWidget(sound_button)

        delete_button = CenterGlyphButton("🗑")
        delete_button.setObjectName("padDeleteButton")
        delete_button.setToolTip("Delete")
        delete_button.clicked.connect(self._request_delete)
        actions_layout.addWidget(delete_button)

        actions_layout.addStretch(1)
        self.actions.setVisible(False)
        root.addWidget(self.actions)

    def mousePressEvent(self, event) -> None:
        if self._bulk_select_enabled and event.button() == Qt.LeftButton:
            self.set_bulk_selected(not self._bulk_selected)
            event.accept()
            return

        if event.button() == Qt.LeftButton and not self._edit_enabled:
            if self._request_play():
                event.accept()
                return

        super().mousePressEvent(event)

    def display_name(self) -> str:
        return self.name_label.text().strip() or "Unnamed"

    def set_emoji(self, emoji: str) -> None:
        self.icon_button.setText(emoji)

    def set_bulk_select_enabled(self, enabled: bool) -> None:
        self._bulk_select_enabled = enabled

        if enabled:
            # Bulk delete is a selection mode, not edit mode.
            # Hide per-pad edit actions while selecting pads to delete.
            self.actions.setVisible(False)
            self.setProperty("edit", "false")
            self.setMinimumHeight(70)
        else:
            self.set_bulk_selected(False)
            self.actions.setVisible(self._edit_enabled)
            self.setProperty("edit", "true" if self._edit_enabled else "false")
            self.setMinimumHeight(100 if self._edit_enabled else 70)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_bulk_selected(self, selected: bool) -> None:
        self._bulk_selected = selected
        self.setProperty("bulkSelected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def is_bulk_selected(self) -> bool:
        return self._bulk_selected

    def _request_delete(self) -> None:
        if self._delete_callback is not None:
            self._delete_callback(self)

    def _request_play(self) -> bool:
        if self._edit_enabled or self._bulk_select_enabled:
            return False
        if not self._slot_key or self._play_callback is None:
            return False
        self._play_callback(self._slot_key)
        return True

    def _request_emoji_palette(self) -> None:
        if not self._edit_enabled:
            self._request_play()
            return
        if self._emoji_callback is not None:
            self._emoji_callback(self)

    def _start_rename(self, event) -> None:
        if not self._edit_enabled:
            return
        self.name_editor.setText(self.name_label.text())
        self.name_label.setVisible(False)
        self.name_editor.setVisible(True)
        self.name_editor.setFocus()
        self.name_editor.selectAll()

    def _finish_rename(self) -> None:
        new_name = self.name_editor.text().strip() or "Unnamed"
        self.name_label.setText(new_name)
        self.name_editor.setVisible(False)
        self.name_label.setVisible(True)

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_enabled = enabled
        self.setProperty("edit", "true" if enabled else "false")
        self.actions.setVisible(enabled)
        self.setMinimumHeight(100 if enabled else 70)
        if not enabled:
            self.name_editor.setVisible(False)
            self.name_label.setVisible(True)
            self.set_bulk_select_enabled(False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()



class PadsPanel(QWidget):
    EMOJIS = [
        "😀", "😃", "😄", "😁", "😆", "😂", "🤣", "🙂", "😉", "😊", "😎", "🤔",
        "😐", "😮", "😱", "🥳", "😈", "🤖", "👻", "💀", "👋", "👏", "👍", "👎",
        "❤️", "💙", "💚", "⭐", "✨", "🔥", "⚡", "💥", "✅", "❌", "⚠️", "🚨",
        "🎵", "🎶", "🎧", "🎤", "📣", "🔔", "🎬", "🎮", "🖱", "⌨️", "🏆", "🎯",
        "🐱", "🐶", "🐸", "🦊", "🐺", "🐲", "🍕", "☕", "🍺", "🚀", "🛸", "🌌",
        "🔊", "🔇", "🔈", "🔉", "📢", "🎺", "🥁", "🎹", "🎸", "🎻", "🎲", "🧨",
        "🟢", "🔴", "🟡", "🔵", "🟣", "🟠", "⬆️", "⬇️", "➡️", "⬅️", "💤", "💫",
    ]

    SAMPLE_PADS = [
        ("Airhorn", "📣", "00:02"),
        ("Click", "🖱", "00:01"),
        ("Bruh", "😐", "00:02"),
        ("Laugh", "😂", "00:03"),
        ("Alert", "🚨", "00:02"),
        ("GG", "🏆", "00:01"),
        ("Intro", "🎬", "00:05"),
        ("Drop", "💥", "00:03"),
    ]

    def __init__(self, detach_callback=None, columns: int = 2, show_detach: bool = True):
        super().__init__()
        self._detach_callback = detach_callback
        self._columns = max(1, columns)
        self._show_detach = show_detach
        self._edit_mode = False
        self._bulk_delete_mode = False
        self._active_emoji_card: SoundPadCard | None = None
        self._soundboard_dialog: SoundboardDialog | None = None
        self.pad_cards: list[SoundPadCard] = []

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("padsTopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(7, 7, 7, 7)
        top_layout.setSpacing(6)

        self.stop_all_button = CenterGlyphButton("■", y_offset=-1)
        self.stop_all_button.setObjectName("padStopAllButton")
        self.stop_all_button.setToolTip("Stop all sounds")
        self.stop_all_button.clicked.connect(self._stop_all_sounds)
        top_layout.addWidget(self.stop_all_button)

        connect = QPushButton("Connect")
        connect.setObjectName("padTopButton")
        connect.setCheckable(True)
        connect.toggled.connect(lambda checked: connect.setText("Connected" if checked else "Connect"))
        top_layout.addWidget(connect)

        if self._show_detach:
            detach = QPushButton("Detach")
            detach.setObjectName("padTopButton")
            detach.clicked.connect(self._detach)
            top_layout.addWidget(detach)

        self.edit = QPushButton("Edit")
        self.edit.setObjectName("padTopButton")
        self.edit.setCheckable(True)
        self.edit.toggled.connect(self._set_edit_mode)
        top_layout.addWidget(self.edit)

        add = CenterGlyphButton("+", y_offset=-1)
        add.setObjectName("padAddButton")
        add.clicked.connect(self._add_pad)
        top_layout.addWidget(add)

        self.bulk_delete = CenterGlyphButton("🗑")
        self.bulk_delete.setObjectName("padBulkDeleteButton")
        self.bulk_delete.setCheckable(True)
        self.bulk_delete.setToolTip("Bulk delete")
        self.bulk_delete.clicked.connect(self._bulk_delete_clicked)
        top_layout.addWidget(self.bulk_delete)

        top_layout.addStretch(1)
        root.addWidget(top_bar)

        self.grid_scroll = AdaptiveScrollArea()
        self.grid_scroll.setObjectName("padsGridScroll")
        self.grid_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        pads_scrollbar = self.grid_scroll.verticalScrollBar()
        pads_scrollbar.setObjectName("padsGridScrollbar")
        pads_scrollbar.setFixedWidth(8)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)

        self.grid_scroll.setWidget(self.grid_host)
        self.grid_scroll._schedule_margin_update()
        root.addWidget(self.grid_scroll, 1)

        for name, icon, meta, slot_key in self._load_real_soundboard_pads():
            self._add_pad(name, icon, meta, slot_key=slot_key)

        self.emoji_overlay = QFrame(self)
        self.emoji_overlay.setObjectName("emojiPalette")
        palette_layout = QGridLayout(self.emoji_overlay)
        palette_layout.setContentsMargins(8, 8, 8, 8)
        palette_layout.setHorizontalSpacing(4)
        palette_layout.setVerticalSpacing(4)

        for index, emoji in enumerate(self.EMOJIS):
            button = QPushButton(emoji)
            button.setObjectName("emojiChoice")
            button.clicked.connect(lambda _checked=False, value=emoji: self._choose_emoji(value))
            palette_layout.addWidget(button, index // 8, index % 8)

        self.emoji_overlay.hide()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.MouseButtonPress and hasattr(self, "emoji_overlay") and self.emoji_overlay.isVisible():
            try:
                global_pos = event.globalPosition().toPoint()
            except AttributeError:
                global_pos = event.globalPos()

            top_left = self.emoji_overlay.mapToGlobal(QPoint(0, 0))
            overlay_rect = QRect(top_left, self.emoji_overlay.size())
            if not overlay_rect.contains(global_pos):
                self.emoji_overlay.hide()

        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_emoji_overlay()

    def _position_emoji_overlay(self) -> None:
        if not hasattr(self, "emoji_overlay"):
            return
        width = min(300, max(220, self.width() - 28))
        height = min(250, max(170, self.height() - 90))
        x = max(8, (self.width() - width) // 2)
        y = max(48, (self.height() - height) // 2)
        self.emoji_overlay.setGeometry(x, y, width, height)

    def _show_emoji_palette(self, card: SoundPadCard) -> None:
        self._active_emoji_card = card
        self._position_emoji_overlay()
        self.emoji_overlay.show()
        self.emoji_overlay.raise_()

    def _choose_emoji(self, emoji: str) -> None:
        if self._active_emoji_card is not None:
            self._active_emoji_card.set_emoji(emoji)
        self.emoji_overlay.hide()


    def _read_soundboard_slots(self) -> list[dict]:
        if not SOUNDBOARD_PATH.is_file():
            return []

        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

        if isinstance(data, dict):
            raw_slots = data.get("slots")
            if raw_slots is None:
                raw_slots = data.get("pads")
        elif isinstance(data, list):
            raw_slots = data
        else:
            raw_slots = []

        if not isinstance(raw_slots, list):
            return []

        return [slot for slot in raw_slots if isinstance(slot, dict)]

    def _icon_for_soundboard_slot(self, slot: dict, path_text: str) -> str:
        explicit = str(slot.get("emoji") or slot.get("icon") or "").strip()
        if explicit:
            return explicit

        output_channel = str(slot.get("output_channel") or "media").strip().lower()
        if output_channel in {"micro", "micro_bus"}:
            return "🎤"
        if output_channel in {"retour", "return-mic", "mic_out"}:
            return "🎙"
        if output_channel == "chat":
            return "💬"
        if output_channel == "game":
            return "🎮"

        suffix = Path(path_text).suffix.lower() if path_text else ""
        if suffix in {".mp3", ".wav", ".ogg", ".flac", ".m4a"}:
            return "🎵"

        return "🎧"

    def _format_soundboard_route(self, value: str) -> str:
        key = str(value or "media").strip().lower()
        names = {
            "all": "ALL",
            "game": "GAME",
            "media": "MEDIA",
            "chat": "CHAT",
            "more": "MORE",
            "retour": "MIC OUT",
            "return-mic": "MIC OUT",
            "mic_out": "MIC OUT",
            "micro": "MICRO",
            "micro_bus": "MICRO",
        }
        return names.get(key, key.upper() if key else "MEDIA")

    def _load_real_soundboard_pads(self) -> list[tuple[str, str, str, str]]:
        pads: list[tuple[str, str, str, str]] = []

        for index, slot in enumerate(self._read_soundboard_slots(), start=1):
            path_text = str(slot.get("path") or "").strip()
            label = str(slot.get("label") or "").strip()

            if not path_text and not label:
                continue

            if not label or label.upper() in {"SOUND", "EMPTY"}:
                label = Path(path_text).stem if path_text else f"Pad {index}"

            route = self._format_soundboard_route(str(slot.get("output_channel") or "media"))
            icon = self._icon_for_soundboard_slot(slot, path_text)
            slot_key = str(slot.get("id") or "").strip() or str(index)

            if path_text:
                sound_path = Path(path_text).expanduser()
                filename = sound_path.name or "sound"
                status = route if sound_path.exists() else "missing"
                meta = f"{status} · {filename}"
            else:
                meta = route

            pads.append((label, icon, meta, slot_key))

        if pads:
            return pads

        if SOUNDBOARD_PATH.is_file():
            return [("No saved sounds", "🎧", "soundboard.json empty", "")]

        return [("No soundboard file", "🎧", "soundboard.json missing", "")]


    def _stop_all_sounds(self) -> None:
        button = getattr(self, "stop_all_button", None)
        if button is not None:
            button.setEnabled(False)
            QTimer.singleShot(180, lambda b=button: b.setEnabled(True))

        local_stopped = False

        dialog = self._soundboard_dialog
        if dialog is not None:
            try:
                dialog.stop_all()
                local_stopped = True
            except Exception:
                pass

        remote_sent = _send_ksh_ipc_payload({"command": "soundboard-stop-all"})

        if not local_stopped and not remote_sent:
            QMessageBox.warning(
                self,
                "Soundboard playback",
                "No active Glass soundboard player was found, and the real app IPC is not reachable.",
            )

    def _soundboard_playback_dialog(self) -> SoundboardDialog:
        dialog = self._soundboard_dialog
        if dialog is None:
            dialog = SoundboardDialog(self)
            dialog.hide()
            self._soundboard_dialog = dialog
        return dialog

    def _play_pad(self, slot_key: str) -> None:
        if self._edit_mode or self._bulk_delete_mode:
            return

        key = str(slot_key or "").strip()
        if not key:
            return

        try:
            dialog = self._soundboard_playback_dialog()
            # Keep Glass read-only, but refresh the hidden playback engine from
            # the current soundboard.json so changes made in the real app apply.
            dialog.slots = dialog._load_slots()
            if not dialog.play_slot_by_key(key):
                QMessageBox.warning(self, "Soundboard playback", "This sound could not be found.")
        except Exception as exc:
            QMessageBox.warning(self, "Soundboard playback", f"Could not play this sound.\n\n{exc}")

    def _detach(self) -> None:
        if self._detach_callback is not None:
            self._detach_callback()

    def _set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self.edit.setText("Done" if enabled else "Edit")

        if enabled and self._bulk_delete_mode:
            # Edit mode and bulk delete mode are separate.
            self._stop_bulk_delete()

        if not enabled:
            self.emoji_overlay.hide()
            self._stop_bulk_delete()

        for card in self.pad_cards:
            card.set_edit_mode(enabled)

    def _add_pad(self, name: str | None = None, icon: str = "🎧", meta: str = "new", slot_key: str = "") -> None:
        if name is None or isinstance(name, bool):
            name = f"New pad {len(self.pad_cards) + 1}"
            icon = "+"
            meta = "empty"
            slot_key = ""

        card = SoundPadCard(
            name,
            icon,
            meta,
            emoji_callback=self._show_emoji_palette,
            delete_callback=self._confirm_delete_card,
            play_callback=self._play_pad,
            slot_key=slot_key,
        )
        card.set_edit_mode(self._edit_mode)
        card.set_bulk_select_enabled(self._bulk_delete_mode)
        self.pad_cards.append(card)
        self._reflow_grid()

    def _reflow_grid(self) -> None:
        for index, card in enumerate(self.pad_cards):
            self.grid.removeWidget(card)
            row = index // self._columns
            col = index % self._columns
            self.grid.addWidget(card, row, col)

        for col in range(self._columns):
            self.grid.setColumnMinimumWidth(col, 0)
            self.grid.setColumnStretch(col, 1)

    def _remove_card(self, card: SoundPadCard) -> None:
        if card not in self.pad_cards:
            return
        self.grid.removeWidget(card)
        self.pad_cards.remove(card)
        if self._active_emoji_card is card:
            self._active_emoji_card = None
            self.emoji_overlay.hide()
        card.setParent(None)
        card.deleteLater()
        self._reflow_grid()

    def _confirm_delete_card(self, card: SoundPadCard) -> None:
        reply = QMessageBox.question(
            self,
            "Delete sound",
            f'Delete "{card.display_name()}"?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._remove_card(card)

    def _bulk_delete_clicked(self) -> None:
        if not self._bulk_delete_mode:
            self._start_bulk_delete()
            return

        self.bulk_delete.setChecked(True)
        selected = [card for card in self.pad_cards if card.is_bulk_selected()]
        count = len(selected)

        if count <= 0:
            QMessageBox.information(self, "Bulk delete", "No sounds selected.")
            return

        reply = QMessageBox.question(
            self,
            "Bulk delete",
            f"Delete {count} selected sound(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for card in list(selected):
            self._remove_card(card)

        self._stop_bulk_delete()

    def _start_bulk_delete(self) -> None:
        # Bulk delete is a selection mode, but the top bar still needs a clear "Done"
        # escape button. Do not enable per-pad edit actions here.
        self._bulk_delete_mode = True
        self.bulk_delete.setChecked(True)

        self.edit.blockSignals(True)
        self.edit.setChecked(True)
        self.edit.blockSignals(False)
        self.edit.setText("Done")

        self.emoji_overlay.hide()

        for card in self.pad_cards:
            card.set_bulk_select_enabled(True)

    def _stop_bulk_delete(self) -> None:
        self._bulk_delete_mode = False
        if hasattr(self, "bulk_delete"):
            self.bulk_delete.setChecked(False)

        for card in getattr(self, "pad_cards", []):
            card.set_bulk_select_enabled(False)

        if hasattr(self, "edit"):
            self.edit.blockSignals(True)
            self.edit.setChecked(bool(self._edit_mode))
            self.edit.blockSignals(False)
            self.edit.setText("Done" if self._edit_mode else "Edit")


class DetachedPadsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub Glass - Pads")
        self.resize(720, 520)

        if APP_ICON.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._background_source = QPixmap(str(APP_BG)) if APP_BG.is_file() else QPixmap()
        self._background_saturation = 0.72
        self._background_darkness = 130
        self._glass_opacity = 178

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        stack = QStackedLayout(central)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackAll)

        self.background_label = QLabel()
        self.background_label.setObjectName("backgroundImage")
        self.background_label.setScaledContents(True)
        self.background_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.background_blur = QGraphicsBlurEffect(self.background_label)
        self.background_blur.setBlurRadius(18.0)
        self.background_label.setGraphicsEffect(self.background_blur)

        self.background_wash = QFrame()
        self.background_wash.setObjectName("backgroundWash")
        self.background_wash.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.background_tint = QFrame()
        self.background_tint.setObjectName("backgroundTint")
        self.background_tint.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        foreground = QWidget()
        foreground.setObjectName("foreground")

        stack.addWidget(self.background_label)
        stack.addWidget(self.background_wash)
        stack.addWidget(self.background_tint)
        stack.addWidget(foreground)
        stack.setCurrentWidget(foreground)

        self.background_label.lower()
        self.background_wash.raise_()
        self.background_tint.raise_()
        foreground.raise_()

        layout = QVBoxLayout(foreground)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_background_controls())

        panel = PadsPanel(detach_callback=None, columns=4, show_detach=False)
        layout.addWidget(panel, 1)

        self._apply_detached_visual_style()
        QTimer.singleShot(0, self._refresh_background)

    def _build_background_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("detachedBgControls")

        grid = QGridLayout(frame)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        title = QLabel("Background")
        title.setObjectName("detachedBgTitle")
        grid.addWidget(title, 0, 0, 1, 4)

        controls = [
            ("Blur", "blur", 18),
            ("Saturation", "saturation", 72),
            ("Darkness", "darkness", 55),
            ("Glass", "glass", 70),
        ]

        for index, (label, key, value) in enumerate(controls, start=1):
            text_label = QLabel(label)
            text_label.setObjectName("detachedBgLabel")
            grid.addWidget(text_label, index, 0)

            slider = NoWheelSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setMinimumHeight(26)
            slider.valueChanged.connect(lambda new_value, item_key=key: self._apply_visual_setting(item_key, new_value))
            grid.addWidget(slider, index, 1, 1, 3)

        return frame

    def _apply_visual_setting(self, key: str, value: int) -> None:
        if key == "blur":
            self.background_blur.setBlurRadius(float(value))
            return

        if key == "saturation":
            self._background_saturation = max(0.0, min(1.0, value / 100.0))
            self._apply_detached_visual_style()
            return

        if key == "darkness":
            self._background_darkness = int(40 + value * 2.0)
            self._apply_detached_visual_style()
            return

        if key == "glass":
            self._glass_opacity = int(70 + value * 1.55)
            self._apply_detached_visual_style()
            return

    def _apply_detached_visual_style(self) -> None:
        glass = max(0, min(255, self._glass_opacity))
        hover = max(0, min(255, glass + 18))
        dim = max(0, min(255, self._background_darkness))
        wash = int(max(0.0, min(1.0, self._background_saturation)) * 42)

        self.setStyleSheet(f"""
QFrame#backgroundWash {{
    background: rgba(90, 130, 255, {wash});
    border: none;
}}

QFrame#backgroundTint {{
    background: rgba(0, 0, 0, {dim});
    border: none;
}}

QFrame#detachedBgControls {{
    background: rgba(0, 0, 0, {max(120, glass - 35)});
    border: none;
    border-radius: 14px;
}}

QFrame#padsTopBar {{
    background: rgba(0, 0, 0, {max(95, glass - 85)});
    border: none;
    border-radius: 12px;
}}

QFrame#soundPadCard {{
    background: rgba(0, 0, 0, {glass});
    border: none;
    border-radius: 12px;
}}

QFrame#soundPadCard:hover {{
    background: rgba(8, 24, 38, {hover});
    border: none;
}}

QFrame#soundPadCard[edit="true"] {{
    background: rgba(11, 31, 47, {max(188, glass)});
    border: none;
}}

QFrame#soundPadCard[bulkSelected="true"] {{
    background: rgba(150, 32, 46, 215);
    border: none;
}}
""")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_background()

    def _refresh_background(self) -> None:
        if self._background_source.isNull():
            self.background_label.clear()
            return

        target = self.background_label.size()
        if target.width() <= 1 or target.height() <= 1:
            return

        scaled = self._background_source.scaled(
            QSize(1280, 720),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.background_label.setPixmap(scaled)

class Drawer(QFrame):
    def __init__(self, visual_callback=None):
        super().__init__()
        self.setObjectName("drawer")
        self.setFixedWidth(358)
        self._visual_callback = visual_callback

        self.stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self.stack)

        self.stack.addWidget(self._apps_page())
        self.stack.addWidget(self._eq_page())
        self.stack.addWidget(self._pads_page())
        self.stack.addWidget(self._settings_page())

    def _make_scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = AdaptiveScrollArea()
        scroll.setWidget(content)
        scroll._update_scroll_margin()
        return scroll

    def _notify_visual(self, key: str, value: int) -> None:
        if self._visual_callback is not None:
            self._visual_callback(key, value)

    def _apps_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Apps")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        root.addWidget(AppsPanel())

        return self._make_scroll_page(content)


    def _eq_page(self) -> QWidget:
        self._eq_presets_by_channel = getattr(
            self,
            "_eq_presets_by_channel",
            {
                "ALL": "KSH Neutral",
                "GAME": "KSH Neutral",
                "MEDIA": "KSH Media",
                "CHAT": "KSH Chat",
                "MORE": "Default",
                "MICRO": "Default",
                "MIC OUT": "Default",
            },
        )

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("EQ editor")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        root.addWidget(QLabel("Channel"))
        self.eq_channel_select = SelectButton(
            ["ALL", "GAME", "MEDIA", "CHAT", "MORE", "MICRO", "MIC OUT"],
            "GAME",
            self._eq_channel_changed,
        )
        root.addWidget(self.eq_channel_select)

        root.addWidget(QLabel("Preset"))
        self.eq_preset_select = SelectButton(
            ["Default", "KSH Neutral", "KSH Game", "KSH Media", "KSH Chat"],
            self._eq_presets_by_channel.get("GAME", "Default"),
            self._eq_preset_changed,
        )
        root.addWidget(self.eq_preset_select)

        bands_card = QFrame()
        bands_card.setObjectName("channelCard")
        bands_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bands_layout = QHBoxLayout(bands_card)
        bands_layout.setContentsMargins(8, 8, 8, 8)
        bands_layout.setSpacing(4)

        bands = [
            ("32", 44), ("64", 42), ("125", 48), ("250", 50), ("500", 54),
            ("1k", 58), ("2k", 66), ("4k", 68), ("8k", 60), ("16k", 52),
        ]

        for label, value in bands:
            col = QVBoxLayout()
            col.setSpacing(3)

            gain = QLabel("+0.0")
            gain.setObjectName("muted")
            gain.setAlignment(Qt.AlignCenter)
            col.addWidget(gain)

            slider = NoWheelSlider(Qt.Vertical)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setMinimumHeight(112)
            slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            col.addWidget(slider, 1, Qt.AlignHCenter)

            freq = QLabel(label)
            freq.setObjectName("muted")
            freq.setAlignment(Qt.AlignCenter)
            col.addWidget(freq)

            bands_layout.addLayout(col)

        root.addWidget(bands_card, 1)

        actions = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primaryButton")
        cancel = QPushButton("Cancel")
        actions.addWidget(save)
        actions.addWidget(cancel)
        root.addLayout(actions)

        return self._make_scroll_page(content)

    def _eq_channel_changed(self, channel: str) -> None:
        preset = self._eq_presets_by_channel.get(channel, "Default")
        self.eq_preset_select.set_current_text(preset)

    def _eq_preset_changed(self, preset: str) -> None:
        channel = self.eq_channel_select.current_text()
        self._eq_presets_by_channel[channel] = preset

    def _settings_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 4, 2, 4)
        root.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        slider_controls = [
            ("Background blur", "blur", 18),
            ("Background saturation", "saturation", 72),
            ("Background darkness", "darkness", 55),
            ("Black glass opacity", "glass", 70),
        ]

        for label, key, value in slider_controls:
            root.addWidget(QLabel(label))
            slider = NoWheelSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setMinimumHeight(34)
            slider.setMaximumHeight(34)
            slider.setTracking(False if key in {"saturation", "blur"} else True)
            slider.valueChanged.connect(lambda new_value, item_key=key: self._notify_visual(item_key, new_value))
            root.addWidget(slider)

        root.addStretch(1)
        return self._make_scroll_page(content)

    def _pads_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Pads hub")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        self.pads_panel = PadsPanel(detach_callback=self._detach_pads, columns=3)
        root.addWidget(self.pads_panel, 1)

        return content

    def _detach_pads(self) -> None:
        window = getattr(self, "_detached_pads_window", None)
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()
            return

        self._detached_pads_window = DetachedPadsWindow()
        self._detached_pads_window.show()

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)


class PreviewWindow(QMainWindow):
    resize_margin = 9

    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub Glass")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(1320, 560)
        self.setMinimumSize(860, 430)

        if APP_ICON.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._background_source = QPixmap(str(APP_BG)) if APP_BG.is_file() else QPixmap()
        self._background_saturation = 0.72
        self._background_darkness = 130
        self._glass_opacity = 178
        self._meter_phase = 0.0
        self._settings_sync_mtime_ns = 0
        self.backend_controller = GlassBackendController(self)
        self.backend_controller.channel_state_changed.connect(self._sync_channel_card_from_backend)
        self.channel_cards: list[ChannelCard] = []

        self._background_refresh_timer = QTimer(self)
        self._background_refresh_timer.setSingleShot(True)
        self._background_refresh_timer.setInterval(80)
        self._background_refresh_timer.timeout.connect(self._refresh_background_now)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)

        stack = QStackedLayout(central)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackAll)

        self.background_label = QLabel()
        self.background_label.setObjectName("backgroundImage")
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setScaledContents(True)
        self.background_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.background_blur = QGraphicsBlurEffect(self.background_label)
        self.background_blur.setBlurRadius(18.0)
        self.background_label.setGraphicsEffect(self.background_blur)

        self.background_wash = QFrame()
        self.background_wash.setObjectName("backgroundWash")
        self.background_wash.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.background_tint = QFrame()
        self.background_tint.setObjectName("backgroundTint")
        self.background_tint.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        foreground = QWidget()
        foreground.setObjectName("foreground")

        stack.addWidget(self.background_label)
        stack.addWidget(self.background_wash)
        stack.addWidget(self.background_tint)
        stack.addWidget(foreground)
        stack.setCurrentWidget(foreground)

        self.background_label.lower()
        self.background_wash.raise_()
        self.background_tint.raise_()
        foreground.raise_()

        outer = QVBoxLayout(foreground)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        content = QFrame()
        content.setObjectName("contentFrame")
        outer.addWidget(content, 1)

        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(9, 9, 9, 9)
        content_layout.setSpacing(10)

        nav = QFrame()
        nav.setObjectName("navRail")
        nav.setFixedWidth(68)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(6, 7, 6, 7)
        nav_layout.setSpacing(7)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_buttons = [
            NavButton("▥", "Mixer"),
            NavButton("▤", "Apps"),
            NavButton("≋", "EQ"),
            NavButton("▦", "Pads"),
            NavButton("⚙", "Settings"),
        ]

        for idx, button in enumerate(nav_buttons):
            self.nav_group.addButton(button, idx)
            nav_layout.addWidget(button)

        nav_layout.addStretch(1)
        nav_buttons[0].setChecked(True)

        content_layout.addWidget(nav)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        cards_row.setContentsMargins(0, 0, 0, 0)

        for channel in CHANNELS:
            name, icon, devices, fallback_value, channel_key = channel
            value, muted = self._channel_state_for_card(channel_key, fallback_value)
            card = ChannelCard(
                name,
                icon,
                devices,
                value,
                channel_key,
                volume_callback=self._send_channel_volume,
                mute_callback=self._set_channel_muted,
            )
            card.sync_from_saved_state(volume=value, muted=muted)
            self.channel_cards.append(card)
            cards_row.addWidget(card)

        content_layout.addLayout(cards_row, 1)

        self.drawer = Drawer(self._apply_visual_setting)
        self.drawer.setVisible(False)
        content_layout.addWidget(self.drawer)

        self.nav_group.idClicked.connect(self._on_nav_clicked)

        self._install_resize_event_filter()
        self._apply_visual_style()
        self._refresh_background()
        self._start_meter_simulation()

        # Glass is the future K-Sounds frontend, not a companion window.
        # Do not poll the old/stable UI settings file to drive live controls:
        # it adds latency and makes the transition architecture wrong.
        self._settings_sync_timer = None

    def _install_resize_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        def enable_tracking(widget: QWidget) -> None:
            widget.setMouseTracking(True)
            for child in widget.findChildren(QWidget):
                child.setMouseTracking(True)

        enable_tracking(self)

    def eventFilter(self, obj, event) -> bool:
        if not isinstance(obj, QWidget):
            return super().eventFilter(obj, event)

        owner_attr = getattr(obj, "window", None)
        try:
            owner = owner_attr() if callable(owner_attr) else owner_attr
        except TypeError:
            owner = None

        if owner is not self:
            return super().eventFilter(obj, event)

        if self.isMaximized():
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseMove:
            edges = self._edges_for_global_pos(event.globalPosition().toPoint())
            self.setCursor(self._cursor_for_edges(edges))
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edges = self._edges_for_global_pos(event.globalPosition().toPoint())
            if edges:
                handle = self.windowHandle()
                edge_flags = Qt.Edges()
                if "left" in edges:
                    edge_flags |= Qt.LeftEdge
                if "right" in edges:
                    edge_flags |= Qt.RightEdge
                if "top" in edges:
                    edge_flags |= Qt.TopEdge
                if "bottom" in edges:
                    edge_flags |= Qt.BottomEdge

                if handle is not None:
                    try:
                        if handle.startSystemResize(edge_flags):
                            event.accept()
                            return True
                    except Exception:
                        pass

        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        try:
            self.backend_controller.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def _on_nav_clicked(self, idx: int) -> None:
        if idx == 0:
            self.drawer.setVisible(False)
            return
        self.drawer.setVisible(True)
        self.drawer.show_page(idx - 1)

    def _apply_visual_setting(self, key: str, value: int) -> None:
        if key == "blur":
            self.background_blur.setBlurRadius(float(value))
            return
        if key == "saturation":
            self._background_saturation = max(0.0, min(2.0, value / 100.0))
            self._apply_visual_style()
            return
        if key == "darkness":
            self._background_darkness = int(40 + value * 2.0)
            self._apply_visual_style()
            return
        if key == "glass":
            self._glass_opacity = int(70 + value * 1.55)
            self._apply_visual_style()
            return

    def _apply_visual_style(self) -> None:
        glass = max(0, min(255, self._glass_opacity))
        hover = max(0, min(255, glass + 18))
        dim = max(0, min(255, self._background_darkness))

        wash = int(max(0.0, min(1.0, self._background_saturation)) * 42)
        dynamic_style = f"""
QFrame#backgroundWash {{
    background: rgba(90, 130, 255, {wash});
    border: none;
}}

QFrame#backgroundTint {{
    background: rgba(0, 0, 0, {dim});
    border: none;
}}

QFrame#navRail,
QFrame#channelCard,
QFrame#drawer {{
    background: rgba(0, 0, 0, {glass});
    border: none;
    border-radius: 15px;
}}

QFrame#channelCard:hover {{
    background: rgba(5, 13, 22, {hover});
    border: none;
}}

QFrame#channelCard[muted="true"] {{
    background: rgba(82, 18, 24, {max(175, glass)});
    border: none;
}}

QFrame#channelCard[muted="true"]:hover {{
    background: rgba(104, 22, 31, {max(190, hover)});
    border: none;
}}
"""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(STYLE + dynamic_style)

    def _sync_channel_cards_from_settings(self, force: bool = False) -> None:
        # Legacy fallback only; intentionally not scheduled.
        # Glass should update from its own frontend/controller state.
        try:
            mtime_ns = SETTINGS_PATH.stat().st_mtime_ns
        except Exception:
            return

        if not force and mtime_ns == self._settings_sync_mtime_ns:
            return

        self._settings_sync_mtime_ns = mtime_ns
        states = _read_saved_mixer_channel_state()
        if not states:
            return

        for card in self.channel_cards:
            key = str(getattr(card, "channel_key", "") or "").strip()
            if not key or key not in states:
                continue
            volume, muted = states[key]
            card.sync_from_saved_state(volume=volume, muted=muted)

    def _channel_state_for_card(self, channel_key: str, fallback_value: int) -> tuple[int, bool]:
        state = self.backend_controller.channel_state(channel_key)
        if state is None:
            return max(0, min(100, int(fallback_value))), False
        return state

    def _sync_channel_card_from_backend(self, channel_key: str, volume: int, muted: bool) -> None:
        key = str(channel_key or "").strip()
        for card in self.channel_cards:
            if str(getattr(card, "channel_key", "") or "").strip() == key:
                card.sync_from_saved_state(volume=volume, muted=muted)
                return

    def _send_channel_volume(self, channel_key: str, value: int) -> bool:
        return self.backend_controller.set_channel_volume(
            channel_key,
            max(0, min(100, int(value))),
        )

    def _set_channel_muted(self, channel_key: str, muted: bool) -> bool:
        return self.backend_controller.set_channel_muted(channel_key, bool(muted))

    def _start_meter_simulation(self) -> None:
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(45)
        self.meter_timer.timeout.connect(self._animate_meters)
        self.meter_timer.start()

    def _animate_meters(self) -> None:
        self._meter_phase += 0.145

        for idx, card in enumerate(self.channel_cards):
            base = max(0.08, min(1.0, card.value / 100.0))
            l_wave = 0.50 + 0.50 * math.sin(self._meter_phase * (1.0 + idx * 0.035) + idx * 0.73)
            r_wave = 0.50 + 0.50 * math.sin(self._meter_phase * (1.13 + idx * 0.04) + idx * 0.91 + 0.8)
            pulse = 0.68 + 0.32 * math.sin(self._meter_phase * 0.31 + idx * 1.7) ** 2

            left = min(1.0, base * (0.20 + 0.72 * l_wave) * pulse)
            right = min(1.0, base * (0.20 + 0.72 * r_wave) * (1.0 - 0.10 * math.sin(idx + self._meter_phase)))
            card.set_meter_levels(left, right)
            card.tick_meters()

    def resizeEvent(self, event) -> None:
        # Do not rescale/reprocess the background during live resize.
        # QLabel scaledContents keeps the preview responsive.
        super().resizeEvent(event)

    def _queue_background_refresh(self) -> None:
        self._background_refresh_timer.start()

    def _saturate_pixmap(self, pixmap: QPixmap) -> QPixmap:
        # V10: no pixel-by-pixel saturation processing.
        # The Settings saturation slider controls a cheap background color wash instead.
        return pixmap

    def _refresh_background(self) -> None:
        self._queue_background_refresh()

    def _refresh_background_now(self) -> None:
        if self._background_source.isNull():
            self.background_label.clear()
            return

        # One cheap low-res background pixmap. QLabel scales it during resize.
        render_size = QSize(1280, 720)
        scaled = self._background_source.scaled(
            render_size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.background_label.setPixmap(scaled)

    def _edges_for_global_pos(self, global_pos: QPoint) -> set[str]:
        local = self.mapFromGlobal(global_pos)
        margin = self.resize_margin
        rect = self.rect()
        edges: set[str] = set()

        if local.x() <= margin:
            edges.add("left")
        elif local.x() >= rect.width() - margin:
            edges.add("right")

        if local.y() <= margin:
            edges.add("top")
        elif local.y() >= rect.height() - margin:
            edges.add("bottom")

        return edges

    def _cursor_for_edges(self, edges: set[str]) -> Qt.CursorShape:
        if {"left", "top"}.issubset(edges) or {"right", "bottom"}.issubset(edges):
            return Qt.SizeFDiagCursor
        if {"right", "top"}.issubset(edges) or {"left", "bottom"}.issubset(edges):
            return Qt.SizeBDiagCursor
        if "left" in edges or "right" in edges:
            return Qt.SizeHorCursor
        if "top" in edges or "bottom" in edges:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = PreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
