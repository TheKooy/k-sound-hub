from __future__ import annotations
import signal
import os

"""
Experimental K-Sounds Hub UI.

This module is intentionally separate from ksound_hub.app.
The stable app stays available as the fallback launcher.
Glass is being migrated into the real K-Sounds frontend.
Backend bindings are added gradually while the stable UI remains a fallback.
"""

import hashlib
import json
import shlex
import re
import math
import secrets
import socket
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QEvent, QObject, QPoint, QProcess, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
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
    QCheckBox,
    QFileDialog,
    QWidgetAction,
    QSystemTrayIcon,
)


from .audio.pipewire_v2_final import PipeWireAudioEngine
from .config import CONFIG_DIR, IPC_SOCKET_PATH
from .control import resolve_ipc_socket_path
from .ipc import AudioIpcServer
from .models import EqProfile
from .settings_store import SettingsStore
from .ui.overlay import OverlayManager
from .ui.soundboard_dialog import SoundboardDialog

PACKAGE_ROOT = Path(__file__).resolve().parent
APP_ICON = PACKAGE_ROOT / "assets/app_icon.png"
APP_BG = PACKAGE_ROOT / "assets/backgrounds/ksound_hub_wallpaper_4k_blurfill_3840x2160.png"
CHANNEL_ICON_DIR = PACKAGE_ROOT / "assets/icons/channels"
CHANNEL_ICON_PATHS = {
    "all": CHANNEL_ICON_DIR / "all.png",
    "game": CHANNEL_ICON_DIR / "game.png",
    "chat": CHANNEL_ICON_DIR / "chat.png",
    "media": CHANNEL_ICON_DIR / "media.png",
    "more": CHANNEL_ICON_DIR / "more.png",
    "micro": CHANNEL_ICON_DIR / "micro.png",
    "return-mic": CHANNEL_ICON_DIR / "return-mic.png",
}
SOUNDBOARD_PATH = CONFIG_DIR / "soundboard.json"

def _qss_url(path: str) -> str:
    return str(path or "").replace("\\", "/").replace('"', '\\"')

SETTINGS_PATH = CONFIG_DIR / "settings.json"


def _read_window_settings_document() -> dict:
    try:
        if SETTINGS_PATH.is_file():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_window_settings_document(data: dict) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


def _window_geometry_rect(window) -> QRect:
    try:
        normal = window.normalGeometry()
        if normal.isValid() and normal.width() > 0 and normal.height() > 0:
            return normal
    except Exception:
        pass
    return window.geometry()


def _save_window_geometry(window, key: str) -> None:
    # Size-only on KDE Wayland: KWin owns window placement, but app-side size
    # memory is reliable and avoids fighting the compositor.
    if not key:
        return

    try:
        size = window.size()
        width = int(size.width())
        height = int(size.height())
        if width < 160 or height < 120:
            rect = _window_geometry_rect(window)
            width = int(rect.width())
            height = int(rect.height())

        if width < 160 or height < 120:
            return

        data = _read_window_settings_document()
        previous = data.get(key)
        if not isinstance(previous, dict):
            previous = {}

        data[key] = {
            "w": width,
            "h": height,
            "maximized": bool(window.isMaximized()),
        }
        _write_window_settings_document(data)
    except Exception:
        pass


def _queue_window_geometry_save(window, key: str, timer: QTimer | None) -> None:
    try:
        if timer is None or not window.isVisible():
            return
        timer.start()
    except Exception:
        pass


def _restore_window_geometry(window, key: str, default_w: int, default_h: int, min_w: int, min_h: int) -> None:
    data = _read_window_settings_document()
    geometry = data.get(key)
    if not isinstance(geometry, dict):
        window.resize(default_w, default_h)
        return

    try:
        width = max(min_w, min(5000, int(geometry.get("w", default_w))))
        height = max(min_h, min(3000, int(geometry.get("h", default_h))))
    except Exception:
        window.resize(default_w, default_h)
        return

    def apply_size() -> None:
        try:
            window.resize(width, height)
            if bool(geometry.get("maximized", False)):
                window.showMaximized()
        except Exception:
            pass

    apply_size()
    QTimer.singleShot(0, apply_size)
    QTimer.singleShot(220, apply_size)
    QTimer.singleShot(900, apply_size)
    QTimer.singleShot(1600, apply_size)


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

GLASS_CHANNEL_OVERLAY_META = {
    "all": ("🌍", "ALL"),
    "game": ("🎮", "GAME"),
    "chat": ("💬", "CHAT"),
    "media": ("🎵", "MEDIA"),
    "more": ("🔊", "MORE"),
    "micro": ("🎤", "MICRO"),
    "return-mic": ("🎧", "MIC OUT"),
}


GLASS_METER_INPUT_SCALE = {
    # MICRO tends to look too hot after the global visual meter boost.
    # This is display-only; it does not change the exported mic volume.
    "micro": 0.28,
}


class GlassBackendController(QObject):
    channel_state_changed = Signal(str, int, bool)
    overlay_message_requested = Signal(str, bool)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self._link_shared_eq_library()
        self.audio_engine = PipeWireAudioEngine()
        self._android_soundboard_dialog: SoundboardDialog | None = None

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
            self._ensure_glass_virtual_audio_buses()
            self.audio_engine.apply_settings(self.settings)
            self._reapply_saved_app_routes()
            self.apply_glass_runtime_routes()
            self.status_changed.emit(self.audio_engine.status_text())
        except Exception as exc:
            self.status_changed.emit(f"Audio backend startup error — {exc}")

    def cleanup_glass_audio_runtime(self) -> None:
        # Full KSounds runtime stop for Glass close/quit.
        # This intentionally does not restart PipeWire and does not kill this Glass process.
        patterns = [
            "ksound_hub.app",
            "ksound_soundboard_web.py",
            "ksound-v2-audio-keepalive",
            "KSH_KEEPALIVE",
            "pipewire -c filter-chain.conf",
            "K-Sounds-Hub-Soundboard-Player",
            "K-Sound-Hub-Soundboard",
            "ffmpeg.*soundboard",
            "pacat.*soundboard",
            "pacat --playback --device=(all|game|chat|media|more|retour|micro_bus|soundboard)",
            "parec --device=(all|game|chat|media|more|retour|micro|micro_bus|soundboard)",
        ]

        for signal in ("-TERM", "-KILL"):
            for pattern in patterns:
                try:
                    subprocess.run(
                        ["pkill", signal, "-f", pattern],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            if signal == "-TERM":
                time.sleep(0.25)

        try:
            self._unload_modules_matching(
                lambda line: (
                    "module-loopback" in line.lower()
                    and (
                        "ksh_mic_physical" in line.lower()
                        or "k-sound-hub-soundboard" in line.lower()
                        or "k-sounds hub mic output monitor" in line.lower()
                        or "k-sound-hub-return-mic-micro" in line.lower()
                        or "k-sound-hub-micro-inject" in line.lower()
                        or "source=soundboard.monitor" in line.lower()
                        or "sink=micro_bus" in line.lower()
                        or "sink=retour" in line.lower()
                    )
                )
            )
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            self._autosave()
        except Exception:
            pass

        try:
            dialog = self._android_soundboard_dialog
            self._android_soundboard_dialog = None
            if dialog is not None:
                try:
                    dialog.stop_all()
                except Exception:
                    pass
                dialog.close()
                dialog.deleteLater()
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

        try:
            self.cleanup_glass_audio_runtime()
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

    def meter_levels(self, channel_key: str) -> tuple[float, float]:
        try:
            left, right = self.audio_engine.meter_levels(self._normalize_channel_key(channel_key))
            return max(0.0, min(1.0, float(left))), max(0.0, min(1.0, float(right)))
        except Exception as exc:
            self.status_changed.emit(f"Meter read error on {channel_key} — {exc}")
            return 0.0, 0.0

    def list_app_streams(self) -> list:
        try:
            return list(self.audio_engine.list_sink_inputs())
        except Exception as exc:
            self.status_changed.emit(f"Apps list error — {exc}")
            return []

    def _stream_rule_for(self, stream) -> str:
        display_name = str(getattr(stream, "display_name", "") or "")
        media_name = str(getattr(stream, "media_name", "") or "").strip()
        node_name = str(getattr(stream, "node_name", "") or "").strip()
        binary_name = str(getattr(stream, "binary_name", "") or "").strip()
        app_name = str(getattr(stream, "app_name", "") or "").strip()

        # Soundboard streams are better identified by media/node names.
        if display_name.upper().startswith("SOUNDBOARD"):
            if media_name:
                return f"media:{media_name}"
            if node_name:
                return f"node:{node_name}"

        if binary_name:
            return f"bin:{binary_name}"
        if app_name:
            return f"app:{app_name}"
        if media_name:
            return f"media:{media_name}"
        if node_name:
            return f"node:{node_name}"
        return ""

    def _stream_matches_rule(self, stream, rule: str) -> bool:
        rule = str(rule or "").strip()
        if not rule:
            return False
        if rule.startswith("bin:"):
            return bool(getattr(stream, "binary_name", "")) and stream.binary_name == rule[4:]
        if rule.startswith("app:"):
            return bool(getattr(stream, "app_name", "")) and stream.app_name == rule[4:]
        if rule.startswith("media:"):
            return bool(getattr(stream, "media_name", "")) and stream.media_name == rule[6:]
        if rule.startswith("node:"):
            return bool(getattr(stream, "node_name", "")) and stream.node_name == rule[5:]
        return False

    def _remember_app_route(self, stream, channel_key: str) -> None:
        target = self._find_channel(channel_key)
        if target is None:
            return

        rule = self._stream_rule_for(stream)
        if not rule:
            return

        for channel in self.settings.channels:
            rules = list(getattr(channel, "app_rules", []) or [])
            channel.app_rules = [item for item in rules if item != rule]

        target.app_rules = list(getattr(target, "app_rules", []) or [])
        if rule not in target.app_rules:
            target.app_rules.append(rule)

        self._save_timer.start()

    def _reapply_saved_app_routes(self) -> None:
        streams = self.list_app_streams()
        if not streams:
            return

        for channel in self.settings.channels:
            channel_key = self._normalize_channel_key(getattr(channel, "key", ""))
            if channel_key not in APP_ROUTE_KEYS:
                continue

            rules = list(getattr(channel, "app_rules", []) or [])
            if not rules:
                continue

            for stream in streams:
                if getattr(stream, "sink_name", "") == channel_key:
                    continue
                if any(self._stream_matches_rule(stream, rule) for rule in rules):
                    self.audio_engine.move_sink_input_to_channel(stream.stream_id, channel_key)

    def move_app_stream(self, stream_id: int, channel_key: str) -> bool:
        key = self._normalize_channel_key(channel_key)
        if key not in APP_ROUTE_KEYS:
            self.status_changed.emit(f"Apps route error — unsupported target: {channel_key}")
            return False

        try:
            wanted_id = int(stream_id)
        except Exception:
            return False

        streams = self.list_app_streams()
        chosen = next((stream for stream in streams if int(stream.stream_id) == wanted_id), None)
        if chosen is None:
            self.status_changed.emit("Apps route error — stream disappeared")
            return False

        try:
            ok = bool(self.audio_engine.move_sink_input_to_channel(wanted_id, key))
        except Exception as exc:
            self.status_changed.emit(f"Apps route error — {exc}")
            return False

        if not ok:
            self.status_changed.emit("Apps route error — PipeWire refused move")
            return False

        self._remember_app_route(chosen, key)
        label = APP_ROUTE_LABEL_BY_KEY.get(key, key.upper())
        name = str(getattr(chosen, "display_name", "") or f"Stream {wanted_id}")
        self.overlay_message_requested.emit(f"▤ {name} → {label}", False)
        self.status_changed.emit(f"Apps route: {name} → {label}")
        return True

    def _link_shared_eq_library(self, source_channel=None) -> None:
        shared_profiles = None
        if source_channel is not None and getattr(source_channel, "eq_profiles", None):
            shared_profiles = source_channel.eq_profiles

        if shared_profiles is None:
            for channel in self.settings.channels:
                if getattr(channel, "eq_profiles", None):
                    shared_profiles = channel.eq_profiles
                    break

        if not shared_profiles:
            shared_profiles = [EqProfile.default()]

        valid_names = {str(getattr(profile, "name", "") or "") for profile in shared_profiles}
        default_name = str(getattr(shared_profiles[0], "name", "") or "Default")

        for channel in self.settings.channels:
            channel.eq_profiles = shared_profiles
            if channel.selected_eq_profile not in valid_names:
                channel.selected_eq_profile = default_name

    def _unique_eq_profile_name(self, channel, wanted: str, *, preserve_current: str | None = None) -> str:
        base = str(wanted or "").strip() or "Preset"
        preserve = str(preserve_current or "").strip()
        existing = {str(getattr(profile, "name", "") or "") for profile in getattr(channel, "eq_profiles", [])}
        if base not in existing or base == preserve:
            return base

        index = 2
        while f"{base} {index}" in existing:
            index += 1
        return f"{base} {index}"

    def _apply_eq_profile_runtime(self, profile_name: str, preferred_channel_key: str | None = None) -> bool:
        profile_name = str(profile_name or "").strip()
        preferred = self._normalize_channel_key(preferred_channel_key or "")
        ok = True

        for channel in self.settings.channels:
            key = self._normalize_channel_key(getattr(channel, "key", ""))
            if key not in APP_ROUTE_KEYS:
                continue
            if key != preferred and str(getattr(channel, "selected_eq_profile", "") or "") != profile_name:
                continue
            try:
                self.audio_engine.apply_channel(self.settings, key)
            except Exception as exc:
                ok = False
                self.status_changed.emit(f"EQ apply error on {key} — {exc}")

        return ok

    def eq_profile_names(self, channel_key: str) -> tuple[list[str], str]:
        channel = self._find_channel(channel_key)
        if channel is None:
            return [], ""

        self._link_shared_eq_library(source_channel=channel)
        profiles = list(getattr(channel, "eq_profiles", []) or [])
        names = [str(getattr(profile, "name", "") or "").strip() for profile in profiles]
        names = [name for name in names if name]

        selected = str(getattr(channel, "selected_eq_profile", "") or "").strip()
        if selected not in names and names:
            selected = names[0]
            channel.selected_eq_profile = selected

        return names, selected

    def _eq_profile_for(self, channel_key: str, profile_name: str | None = None):
        channel = self._find_channel(channel_key)
        if channel is None:
            return None, None

        self._link_shared_eq_library(source_channel=channel)
        profiles = list(getattr(channel, "eq_profiles", []) or [])
        if not profiles:
            channel.eq_profiles = [EqProfile.default()]
            profiles = channel.eq_profiles

        wanted = str(profile_name or getattr(channel, "selected_eq_profile", "") or "").strip()
        for profile in profiles:
            if str(getattr(profile, "name", "") or "").strip() == wanted:
                return channel, profile

        channel.selected_eq_profile = str(getattr(profiles[0], "name", "") or "Default")
        return channel, profiles[0]

    def eq_profile_bands(self, channel_key: str, profile_name: str | None = None) -> list[tuple[float, float, float]]:
        _channel, profile = self._eq_profile_for(channel_key, profile_name)
        if profile is None:
            return []

        bands = []
        for band in list(getattr(profile, "bands", []) or []):
            try:
                bands.append((float(band.frequency), float(band.gain_db), float(band.q)))
            except Exception:
                continue
        return bands

    def select_eq_profile(self, channel_key: str, profile_name: str) -> bool:
        channel, profile = self._eq_profile_for(channel_key, profile_name)
        if channel is None or profile is None:
            return False

        channel.selected_eq_profile = str(getattr(profile, "name", "") or profile_name)
        if not self._apply_eq_profile_runtime(channel.selected_eq_profile, channel.key):
            return False

        self._save_timer.start()
        label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("≋", channel.name))[1]
        self.overlay_message_requested.emit(f"≋ {label} EQ → {channel.selected_eq_profile}", False)
        return True

    def create_eq_profile(self, channel_key: str, name: str) -> str:
        channel = self._find_channel(channel_key)
        if channel is None:
            return ""

        self._link_shared_eq_library(source_channel=channel)
        profile_name = self._unique_eq_profile_name(channel, name or "New preset")
        profile = EqProfile.default(name=profile_name)
        channel.eq_profiles.append(profile)
        channel.selected_eq_profile = profile.name

        self._save_timer.start()
        self._apply_eq_profile_runtime(profile.name, channel.key)
        label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("≋", channel.name))[1]
        self.overlay_message_requested.emit(f"≋ {label} EQ new → {profile.name}", False)
        return profile.name

    def duplicate_eq_profile(self, channel_key: str, profile_name: str, new_name: str) -> str:
        channel, profile = self._eq_profile_for(channel_key, profile_name)
        if channel is None or profile is None:
            return ""

        wanted = new_name or f"{getattr(profile, 'name', 'Preset')} copy"
        clone_name = self._unique_eq_profile_name(channel, wanted)
        clone = EqProfile.from_dict(profile.to_dict())
        clone.name = clone_name
        channel.eq_profiles.append(clone)
        channel.selected_eq_profile = clone.name

        self._save_timer.start()
        self._apply_eq_profile_runtime(clone.name, channel.key)
        label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("≋", channel.name))[1]
        self.overlay_message_requested.emit(f"≋ {label} EQ duplicate → {clone.name}", False)
        return clone.name

    def rename_eq_profile(self, channel_key: str, profile_name: str, new_name: str) -> str:
        channel, profile = self._eq_profile_for(channel_key, profile_name)
        if channel is None or profile is None:
            return ""

        old_name = str(getattr(profile, "name", "") or "").strip()
        renamed = self._unique_eq_profile_name(channel, new_name, preserve_current=old_name)
        if not renamed:
            return ""

        profile.name = renamed
        for item in self.settings.channels:
            if str(getattr(item, "selected_eq_profile", "") or "") == old_name:
                item.selected_eq_profile = renamed

        channel.selected_eq_profile = renamed
        self._save_timer.start()
        self._apply_eq_profile_runtime(renamed, channel.key)
        label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("≋", channel.name))[1]
        self.overlay_message_requested.emit(f"≋ {label} EQ rename → {renamed}", False)
        return renamed

    def delete_eq_profile(self, channel_key: str, profile_name: str) -> str:
        channel, profile = self._eq_profile_for(channel_key, profile_name)
        if channel is None or profile is None:
            return ""

        self._link_shared_eq_library(source_channel=channel)
        profiles = list(getattr(channel, "eq_profiles", []) or [])
        if len(profiles) <= 1:
            self.status_changed.emit("EQ delete blocked — at least one preset must remain")
            return ""

        deleted_name = str(getattr(profile, "name", "") or profile_name)
        remaining = [item for item in profiles if str(getattr(item, "name", "") or "") != deleted_name]
        if not remaining:
            return ""

        replacement = str(getattr(remaining[0], "name", "") or "Default")
        for item in self.settings.channels:
            item.eq_profiles = remaining
            if str(getattr(item, "selected_eq_profile", "") or "") == deleted_name:
                item.selected_eq_profile = replacement

        channel.selected_eq_profile = replacement
        self._save_timer.start()
        self._apply_eq_profile_runtime(replacement, channel.key)
        label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("≋", channel.name))[1]
        self.overlay_message_requested.emit(f"≋ {label} EQ deleted → {deleted_name}", False)
        return replacement

    def set_eq_band_gain(self, channel_key: str, band_index: int, gain_db: float, profile_name: str | None = None) -> bool:
        channel, profile = self._eq_profile_for(channel_key, profile_name)
        if channel is None or profile is None:
            return False

        bands = list(getattr(profile, "bands", []) or [])
        try:
            band = bands[int(band_index)]
        except Exception:
            return False

        try:
            band.gain_db = max(-12.0, min(12.0, round(float(gain_db) * 2.0) / 2.0))
        except Exception:
            return False

        profile_name = str(getattr(profile, "name", "") or getattr(channel, "selected_eq_profile", ""))
        channel.selected_eq_profile = profile_name
        if not self._apply_eq_profile_runtime(profile_name, channel.key):
            return False

        self._save_timer.start()
        return True

    def _overlay_text(self, channel, hint: str) -> str:
        icon, label = GLASS_CHANNEL_OVERLAY_META.get(channel.key, ("🎚", channel.name))
        if hint == "mute":
            return f"{icon} {label} {'🔇' if channel.muted else '🔊'}"
        return f"{icon} {label} {int(channel.volume)}%"

    def set_channel_volume(self, channel_key: str, value: int) -> bool:
        return self._apply_mixer_action(channel_key, "set-volume", volume=value)

    def set_channel_muted(self, channel_key: str, muted: bool) -> bool:
        return self._apply_mixer_action(channel_key, "set-mute", muted=muted)

    def _pactl_blocks(self, kind: str) -> list[dict[str, str]]:
        result = self._pactl("list", kind)
        if result.returncode != 0:
            return []

        blocks: list[dict[str, str]] = []
        current: dict[str, str] | None = None

        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            if re.match(r"^(Sink|Source) #\d+", line):
                if current:
                    blocks.append(current)
                current = {}
                continue

            if current is None:
                continue

            stripped = line.strip()
            if stripped.startswith("Name:"):
                current["name"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Description:"):
                current["description"] = stripped.split(":", 1)[1].strip()

        if current:
            blocks.append(current)

        return blocks

    def _dedupe_device_label(self, label: str, name: str, used: set[str]) -> str:
        clean = str(label or name or "Unknown device").strip()
        if clean not in used:
            used.add(clean)
            return clean

        short = str(name or "").strip()
        candidate = f"{clean} [{short}]" if short else clean
        index = 2
        while candidate in used:
            candidate = f"{clean} [{index}]"
            index += 1
        used.add(candidate)
        return candidate

    def available_output_targets(self) -> list[tuple[str, str]]:
        internal = {
            "all",
            "game",
            "chat",
            "media",
            "more",
            "retour",
            "micro_bus",
            "soundboard",
        }

        targets: list[tuple[str, str]] = []
        used: set[str] = set()

        for block in self._pactl_blocks("sinks"):
            name = str(block.get("name") or "").strip()
            if not name or name in internal:
                continue
            if name.endswith(".monitor"):
                continue

            description = str(block.get("description") or name).strip()
            lowered = f"{name} {description}".lower()
            if any(token in lowered for token in ["k-sound", "ksounds", "soundboard", "micro-bus", "retour-micro"]):
                continue

            label = self._dedupe_device_label(description, name, used)
            targets.append((label, name))

        if not targets:
            targets = list(PHYSICAL_OUTPUT_TARGETS)

        return targets

    def available_input_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        used: set[str] = set()

        for block in self._pactl_blocks("sources"):
            name = str(block.get("name") or "").strip()
            if not name or name.endswith(".monitor"):
                continue

            description = str(block.get("description") or name).strip()
            lowered = f"{name} {description}".lower()
            if any(token in lowered for token in ["k-sound-hub-soundboard", "soundboard", "retour"]):
                continue

            label = self._dedupe_device_label(description, name, used)
            targets.append((label, name))

        if not targets:
            targets = list(PHYSICAL_INPUT_TARGETS) if "PHYSICAL_INPUT_TARGETS" in globals() else [("MICRO", "micro")]

        return targets

    def resolve_output_label(self, label: str) -> str:
        wanted = str(label or "").strip()
        dynamic = dict(self.available_output_targets())
        if wanted in dynamic:
            return dynamic[wanted]
        return PHYSICAL_OUTPUT_BY_LABEL.get(wanted, "")

    def resolve_input_label(self, label: str) -> str:
        wanted = str(label or "").strip()
        dynamic = dict(self.available_input_targets())
        if wanted in dynamic:
            return dynamic[wanted]
        if "PHYSICAL_INPUT_BY_LABEL" in globals():
            return PHYSICAL_INPUT_BY_LABEL.get(wanted, "")
        return ""

    def label_for_target(self, target: str, *, input_device: bool = False) -> str:
        wanted = str(target or "").strip()
        pairs = self.available_input_targets() if input_device else self.available_output_targets()
        for label, name in pairs:
            if name == wanted:
                return label

        if input_device and "PHYSICAL_INPUT_LABEL_BY_SOURCE" in globals():
            return PHYSICAL_INPUT_LABEL_BY_SOURCE.get(wanted, wanted)
        return PHYSICAL_OUTPUT_LABEL_BY_SINK.get(wanted, wanted)

    def _normalize_soundboard_output_key(self, channel_key: str) -> str:
        raw = str(channel_key or "").strip()
        lowered = raw.lower().replace("_", "-")
        aliases = {
            "mic out": "return-mic",
            "mic-out": "return-mic",
            "return mic": "return-mic",
            "return-mic": "return-mic",
            "retour": "return-mic",
        }
        lowered = aliases.get(lowered, lowered)
        key = self._normalize_channel_key(lowered)
        if key in {"all", "game", "chat", "media", "more", "return-mic"}:
            return key
        return "media"

    def _read_soundboard_document(self) -> dict:
        try:
            if SOUNDBOARD_PATH.is_file():
                loaded = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            else:
                loaded = {}
            if isinstance(loaded, list):
                return {"slots": loaded}
            if isinstance(loaded, dict):
                if not isinstance(loaded.get("slots"), list):
                    loaded["slots"] = []
                return loaded
        except Exception:
            pass
        return {"slots": []}

    def _write_soundboard_document(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                data = {"slots": []}
            if not isinstance(data.get("slots"), list):
                data["slots"] = []
            SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            self.status_changed.emit(f"Soundboard config save error — {exc}")

    def _soundboard_send_to_micro_config(self) -> bool:
        data = self._read_soundboard_document()
        value = data.get("send_to_micro")
        if isinstance(value, bool):
            return value
        slots = data.get("slots", [])
        if isinstance(slots, list):
            return any(bool(slot.get("send_to_micro")) for slot in slots if isinstance(slot, dict))
        return False

    def _soundboard_output_config(self) -> str:
        data = self._read_soundboard_document()

        root = str(data.get("output_channel") or "").strip()
        if root:
            return self._normalize_soundboard_output_key(root)

        # Legacy flag from previous UI attempts.
        if bool(data.get("monitor_to_mic_out")):
            return "return-mic"

        counts: dict[str, int] = {}
        for slot in data.get("slots", []):
            if not isinstance(slot, dict):
                continue
            key = self._normalize_soundboard_output_key(str(slot.get("output_channel") or ""))
            counts[key] = counts.get(key, 0) + 1
        if counts:
            return max(counts.items(), key=lambda item: item[1])[0]
        return "media"

    def _pactl(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["pactl", *[str(arg) for arg in args]],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _list_pulse_modules_short(self) -> list[str]:
        result = self._pactl("list", "short", "modules")
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    def _unload_matching_modules(self, predicate) -> None:
        for line in self._list_pulse_modules_short():
            parts = line.split("\t", 2)
            if not parts:
                continue
            module_id = parts[0].strip()
            if not module_id.isdigit():
                continue
            try:
                if predicate(line):
                    self._pactl("unload-module", module_id)
            except Exception:
                pass

    def apply_soundboard_runtime_routes(self) -> None:
        output_key = self._soundboard_output_config()
        send_to_micro = self._soundboard_send_to_micro_config()
        output_sink = {
            "all": "all",
            "game": "game",
            "chat": "chat",
            "media": "media",
            "more": "more",
            "return-mic": "retour",
        }.get(output_key, "media")

        def is_old_soundboard_route(line: str) -> bool:
            lowered = line.lower()
            return (
                "module-loopback" in lowered
                and "source=soundboard.monitor" in lowered
                and any(f"sink={sink}" in lowered for sink in ["all", "game", "chat", "media", "more", "retour", "micro_bus"])
            )

        self._unload_matching_modules(is_old_soundboard_route)

        self._pactl(
            "load-module",
            "module-loopback",
            "source=soundboard.monitor",
            f"sink={output_sink}",
            "latency_msec=32",
            "source_dont_move=true",
            "sink_dont_move=true",
            "channels=2",
            "sink_input_properties=media.name=K-Sound-Hub-Soundboard-To-Output",
        )

        if send_to_micro:
            self._pactl(
                "load-module",
                "module-loopback",
                "source=soundboard.monitor",
                "sink=micro_bus",
                "latency_msec=32",
                "source_dont_move=true",
                "sink_dont_move=true",
                "channels=2",
                "sink_input_properties=media.name=K-Sound-Hub-Soundboard-To-Micro",
            )

    def apply_return_mic_runtime_route(self) -> None:
        state = self.return_mic_route_state()
        enabled = bool(state.get("micro"))

        def is_old_return_mic_micro_route(line: str) -> bool:
            lowered = line.lower()
            return (
                "module-loopback" in lowered
                and "sink=retour" in lowered
                and (
                    "source=micro" in lowered
                    or "k-sound-hub-return-mic-micro" in lowered
                )
            )

        self._unload_matching_modules(is_old_return_mic_micro_route)

        if enabled:
            self._pactl(
                "load-module",
                "module-loopback",
                "source=micro",
                "sink=retour",
                "latency_msec=20",
                "source_dont_move=true",
                "sink_dont_move=true",
                "channels=2",
                "sink_input_properties=media.name=K-Sound-Hub-Return-Mic-Micro",
            )

    def _sync_soundboard_settings_links(self, output_key: str, send_to_micro: bool) -> None:
        output_key = self._normalize_soundboard_output_key(output_key)

        for key in ("all", "game", "chat", "media", "more", "return-mic", "micro"):
            channel = self._find_channel(key)
            if channel is None:
                continue

            linked = [
                str(item).strip().lower()
                for item in getattr(channel, "linked_channels", []) or []
                if str(item).strip()
            ]
            linked = [item for item in linked if item != "soundboard"]

            if key == output_key:
                linked.append("soundboard")
            if key == "micro" and send_to_micro:
                linked.append("soundboard")

            channel.linked_channels = linked

    def _normalize_soundboard_output_key(self, channel_key: str) -> str:
        raw = str(channel_key or "").strip().lower().replace("_", "-")
        aliases = {
            "mic out": "return-mic",
            "mic-out": "return-mic",
            "return mic": "return-mic",
            "return-mic": "return-mic",
            "retour": "return-mic",
        }
        raw = aliases.get(raw, raw)
        key = self._normalize_channel_key(raw)
        if key in {"all", "game", "chat", "media", "more", "return-mic"}:
            return key
        return "media"

    def _read_soundboard_document(self) -> dict:
        try:
            if SOUNDBOARD_PATH.is_file():
                loaded = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            else:
                loaded = {}
            if isinstance(loaded, list):
                loaded = {"slots": loaded}
            if isinstance(loaded, dict):
                if not isinstance(loaded.get("slots"), list):
                    loaded["slots"] = []
                return loaded
        except Exception:
            pass
        return {"slots": []}

    def _write_soundboard_document(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                data = {"slots": []}
            if not isinstance(data.get("slots"), list):
                data["slots"] = []
            SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            self.status_changed.emit(f"Soundboard config save error — {exc}")

    def _read_settings_document(self) -> dict:
        try:
            path = CONFIG_DIR / "settings.json"
            if path.is_file():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
        except Exception:
            pass
        return {}

    def _write_settings_document(self, data: dict) -> None:
        try:
            path = CONFIG_DIR / "settings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _pactl(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["pactl", *[str(arg) for arg in args]],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _pulse_modules(self) -> list[str]:
        result = self._pactl("list", "short", "modules")
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    def _unload_modules_matching(self, predicate) -> None:
        for line in self._pulse_modules():
            parts = line.split("\t", 2)
            if not parts:
                continue
            module_id = parts[0].strip()
            if not module_id.isdigit():
                continue
            try:
                if predicate(line):
                    self._pactl("unload-module", module_id)
            except Exception:
                pass

    def _ensure_null_sink(self, sink_name: str, description: str) -> bool:
        name = str(sink_name or "").strip()
        label = str(description or name).strip()
        if not name:
            return False
        if self._sink_exists(name):
            return True

        self._pactl(
            "load-module",
            "module-null-sink",
            f"sink_name={name}",
            f"sink_properties=device.description={label}",
            "channels=2",
            "rate=48000",
        )
        time.sleep(0.04)
        return self._sink_exists(name)

    def _ensure_micro_endpoint(self) -> bool:
        if not self._ensure_null_sink("micro_bus", "🎤MICRO-BUS"):
            return False

        if not self._source_exists("micro"):
            self._pactl(
                "load-module",
                "module-remap-source",
                "master=micro_bus.monitor",
                "source_name=micro",
                "source_properties=device.description=🎤MICRO",
            )
            time.sleep(0.04)

        return self._source_exists("micro")

    def _ensure_glass_virtual_audio_buses(self) -> bool:
        # Glass is the frontend/runtime owner now. Do not rely on the old stable
        # UI or an external keepalive to create these logical channel sinks.
        wanted = (
            ("all", "🌍ALL"),
            ("game", "🎮GAME"),
            ("chat", "💬CHAT"),
            ("media", "🎵MEDIA"),
            ("more", "🔊MORE"),
            ("retour", "🎧MIC OUT"),
        )

        ok = True
        for sink_name, description in wanted:
            if not self._ensure_null_sink(sink_name, description):
                ok = False

        if not self._ensure_micro_endpoint():
            ok = False

        if not ok:
            self.status_changed.emit("Glass virtual audio buses incomplete — routing may be unsafe")
        return ok

    def _sink_exists(self, sink_name: str) -> bool:
        wanted = str(sink_name or "").strip()
        if not wanted:
            return False
        result = self._pactl("list", "short", "sinks")
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == wanted:
                return True
        return False

    def _source_exists(self, source_name: str) -> bool:
        wanted = str(source_name or "").strip()
        if not wanted:
            return False
        result = self._pactl("list", "short", "sources")
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == wanted:
                return True
        return False

    def _unload_soundboard_monitor_loopbacks(self) -> None:
        self._unload_modules_matching(
            lambda line: (
                "module-loopback" in line.lower()
                and "source=soundboard.monitor" in line.lower()
            )
        )

    def _unload_rigid_soundboard_output_loopbacks(self) -> None:
        # Old route instances were loaded with sink_dont_move=true, which makes
        # pactl move-sink-input fail and forces unload/reload on every output
        # switch. Remove only that old Soundboard-To-Output route; keep MICRO.
        self._unload_modules_matching(
            lambda line: (
                "module-loopback" in line.lower()
                and "source=soundboard.monitor" in line.lower()
                and "sink=micro_bus" not in line.lower()
                and "sink_dont_move=true" in line.lower()
            )
        )

    def _ensure_soundboard_bus(self) -> bool:
        # Glass plays every pad into the private soundboard sink, then routes
        # soundboard.monitor to MEDIA / MIC OUT / MICRO. If the private bus is
        # missing, a loopback that says source=soundboard.monitor can become a
        # stale or wrong live route. Repair the bus before accepting any route.
        if self._sink_exists("soundboard") and self._source_exists("soundboard.monitor"):
            return True

        self._unload_soundboard_monitor_loopbacks()

        if self._sink_exists("soundboard") and not self._source_exists("soundboard.monitor"):
            self._unload_modules_matching(
                lambda line: (
                    "module-null-sink" in line.lower()
                    and "sink_name=soundboard" in line.lower()
                )
            )

        if not self._sink_exists("soundboard"):
            self._pactl(
                "load-module",
                "module-null-sink",
                "sink_name=soundboard",
                "sink_properties=device.description=🎛SOUNDBOARD media.name=K-Sound-Hub-Soundboard-Bus",
                "channels=2",
                "rate=48000",
            )
            time.sleep(0.05)

        ok = self._sink_exists("soundboard") and self._source_exists("soundboard.monitor")
        if not ok:
            self.status_changed.emit("Soundboard bus missing — cannot route Soundboard output safely")
        return ok

    def _soundboard_output_config(self) -> str:
        data = self._read_soundboard_document()

        raw = str(data.get("output_channel") or "").strip()
        if raw:
            return self._normalize_soundboard_output_key(raw)

        if bool(data.get("monitor_to_mic_out")):
            return "return-mic"

        return "media"

    def _soundboard_send_to_micro_config(self) -> bool:
        data = self._read_soundboard_document()
        value = data.get("send_to_micro")
        if isinstance(value, bool):
            return value
        return False

    def _return_mic_micro_enabled(self) -> bool:
        data = self._read_settings_document()
        if isinstance(data.get("glass_return_mic_micro_enabled"), bool):
            return bool(data.get("glass_return_mic_micro_enabled"))

        for channel in data.get("channels", []) if isinstance(data.get("channels"), list) else []:
            if isinstance(channel, dict) and channel.get("key") == "return-mic":
                linked = {str(item).strip().lower() for item in channel.get("linked_channels", []) or []}
                return bool({"micro", "micro-final"} & linked)
        return False

    def _save_return_mic_micro_enabled(self, enabled: bool) -> None:
        data = self._read_settings_document()
        data["glass_return_mic_micro_enabled"] = bool(enabled)

        # Do not use linked_channels for these Glass-only runtime routes anymore.
        for channel in data.get("channels", []) if isinstance(data.get("channels"), list) else []:
            if isinstance(channel, dict) and channel.get("key") == "return-mic":
                linked = [
                    str(item).strip().lower()
                    for item in channel.get("linked_channels", []) or []
                    if str(item).strip().lower() not in {"micro", "micro-final", "soundboard"}
                ]
                channel["linked_channels"] = linked

        self._write_settings_document(data)

    def _sink_inputs_by_media_name(self, media_name: str) -> list[str]:
        result = self._pactl("list", "sink-inputs")
        if result.returncode != 0:
            return []

        wanted = str(media_name or "").strip()
        ids: list[str] = []
        current_id: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_id, current_lines
            if current_id is not None:
                block = "\n".join(current_lines)
                if f'media.name = "{wanted}"' in block or f"media.name = {wanted}" in block:
                    ids.append(current_id)
            current_id = None
            current_lines = []

        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            m = re.match(r"Sink Input #(\d+)", line)
            if m:
                flush()
                current_id = m.group(1)
                current_lines = [line]
            elif current_id is not None:
                current_lines.append(line)

        flush()
        return ids

    def _sink_input_sink_names_by_media_name(self, media_name: str) -> list[str]:
        wanted = str(media_name or "").strip()
        if not wanted:
            return []

        sink_names_by_index: dict[str, str] = {}
        sinks = self._pactl("list", "short", "sinks")
        if sinks.returncode == 0:
            for line in sinks.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    sink_names_by_index[parts[0]] = parts[1]

        result = self._pactl("list", "sink-inputs")
        if result.returncode != 0:
            return []

        names: list[str] = []
        current_sink_index: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_sink_index, current_lines
            if current_sink_index is None:
                current_lines = []
                return
            block = "\n".join(current_lines)
            if f'media.name = "{wanted}"' in block or f"media.name = {wanted}" in block:
                names.append(sink_names_by_index.get(current_sink_index, current_sink_index))
            current_sink_index = None
            current_lines = []

        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            if re.match(r"Sink Input #(\d+)", line):
                flush()
                current_sink_index = None
                current_lines = [line]
                continue

            if not current_lines:
                continue

            stripped = line.strip()
            if stripped.startswith("Sink:"):
                current_sink_index = stripped.split(":", 1)[1].strip()
            current_lines.append(line)

        flush()
        return names

    def _unmute_soundboard_output_streams(self) -> None:
        for stream_id in self._sink_inputs_by_media_name("K-Sound-Hub-Soundboard-To-Output"):
            self._pactl("set-sink-input-mute", stream_id, "0")
            self._pactl("set-sink-input-volume", stream_id, "100%")

    def _move_soundboard_output_streams(self, sink: str) -> bool:
        target = str(sink or "").strip()
        if not target or not self._sink_exists(target):
            return False

        stream_ids = self._sink_inputs_by_media_name("K-Sound-Hub-Soundboard-To-Output")
        if not stream_ids:
            return False

        moved = False
        for stream_id in stream_ids:
            result = self._pactl("move-sink-input", stream_id, target)
            if result.returncode == 0:
                moved = True

        if moved:
            self._unmute_soundboard_output_streams()
        return moved

    def _soundboard_output_sink_for_key(self, output_key: str) -> str:
        return {
            "all": "all",
            "game": "game",
            "chat": "chat",
            "media": "media",
            "more": "more",
            "return-mic": "retour",
        }.get(self._normalize_soundboard_output_key(output_key), "media")

    def _soundboard_output_loopback_ok(self, output_key: str) -> bool:
        if not self._sink_exists("soundboard") or not self._source_exists("soundboard.monitor"):
            return False

        sink = self._soundboard_output_sink_for_key(output_key)
        if not self._sink_exists(sink):
            return False

        matching_ids: list[str] = []
        for line in self._pulse_modules():
            parts = line.split("\t", 2)
            module_id = parts[0].strip() if parts else ""
            low = line.lower()
            if not ("module-loopback" in low and "source=soundboard.monitor" in low):
                continue
            if "sink=micro_bus" in low:
                continue
            if f"sink={sink}" in low:
                if module_id.isdigit():
                    matching_ids.append(module_id)
            elif module_id.isdigit():
                self._pactl("unload-module", module_id)

        for module_id in matching_ids[:-1]:
            self._pactl("unload-module", module_id)

        if len(matching_ids) != 1:
            return False

        actual_sinks = self._sink_input_sink_names_by_media_name("K-Sound-Hub-Soundboard-To-Output")
        if actual_sinks and (sink not in actual_sinks or any(name != sink for name in actual_sinks)):
            # PipeWire-pulse can keep a loopback module with args sink=<logical>
            # while its stream has fallen back to the default physical sink if
            # the logical sink was missing at load time. Treat that as stale.
            for module_id in matching_ids:
                self._pactl("unload-module", module_id)
            return False

        return True

    def _soundboard_micro_loopback_ok(self) -> bool:
        if not self._sink_exists("soundboard") or not self._source_exists("soundboard.monitor"):
            return False
        if not self._sink_exists("micro_bus"):
            return False

        matching_ids: list[str] = []
        for line in self._pulse_modules():
            parts = line.split("\t", 2)
            module_id = parts[0].strip() if parts else ""
            low = line.lower()
            if (
                "module-loopback" in low
                and "source=soundboard.monitor" in low
                and "sink=micro_bus" in low
                and module_id.isdigit()
            ):
                matching_ids.append(module_id)

        for module_id in matching_ids[:-1]:
            self._pactl("unload-module", module_id)

        if len(matching_ids) != 1:
            return False

        actual_sinks = self._sink_input_sink_names_by_media_name("K-Sound-Hub-Soundboard-To-Micro")
        if actual_sinks and ("micro_bus" not in actual_sinks or any(name != "micro_bus" for name in actual_sinks)):
            for module_id in matching_ids:
                self._pactl("unload-module", module_id)
            return False

        return True

    def _load_soundboard_output_loopback(self, output_key: str) -> None:
        self._ensure_glass_virtual_audio_buses()
        if not self._ensure_soundboard_bus():
            return

        sink = self._soundboard_output_sink_for_key(output_key)
        if not self._sink_exists(sink):
            self._unload_modules_matching(
                lambda line: (
                    "module-loopback" in line.lower()
                    and "source=soundboard.monitor" in line.lower()
                    and "sink=micro_bus" not in line.lower()
                )
            )
            self.status_changed.emit(f"Soundboard output sink missing — {sink}")
            return

        self._unload_rigid_soundboard_output_loopbacks()

        # Prefer moving the existing Soundboard-To-Output loopback stream. This
        # avoids destroying/recreating the loopback on every output switch, which
        # produces audible pops/crackles even when no pad is playing.
        if self._move_soundboard_output_streams(sink):
            return

        # Critical for pads latency: if the correct listening route already
        # exists, do NOT unload/reload it before each sound.
        if self._soundboard_output_loopback_ok(output_key):
            self._unmute_soundboard_output_streams()
            return

        self._unload_modules_matching(
            lambda line: (
                "module-loopback" in line.lower()
                and "source=soundboard.monitor" in line.lower()
                and "sink=micro_bus" not in line.lower()
            )
        )

        self._pactl(
            "load-module",
            "module-loopback",
            "source=soundboard.monitor",
            f"sink={sink}",
            "latency_msec=32",
            "source_dont_move=true",
            "channels=2",
            "sink_input_properties=media.name=K-Sound-Hub-Soundboard-To-Output",
        )

        time.sleep(0.04)
        self._unmute_soundboard_output_streams()

    def _load_soundboard_micro_loopback(self, enabled: bool) -> None:
        if enabled:
            self._ensure_glass_virtual_audio_buses()
            if not self._ensure_soundboard_bus():
                return

        exists = self._soundboard_micro_loopback_ok()

        # Critical for pads latency: do not reload the MICRO route on every pad.
        if enabled and exists:
            return
        if not enabled and not exists:
            return

        self._unload_modules_matching(
            lambda line: (
                "module-loopback" in line.lower()
                and "source=soundboard.monitor" in line.lower()
                and "sink=micro_bus" in line.lower()
            )
        )

        if enabled:
            self._pactl(
                "load-module",
                "module-loopback",
                "source=soundboard.monitor",
                "sink=micro_bus",
                "latency_msec=32",
                "source_dont_move=true",
                "sink_dont_move=true",
                "channels=2",
                "sink_input_properties=media.name=K-Sound-Hub-Soundboard-To-Micro",
            )

    def _return_mic_source_config(self) -> str:
        data = self._read_settings_document()
        # Off must be really Off. Do not infer from old glass_return_mic_micro_enabled.
        return str(data.get("glass_return_mic_source") or "").strip()

    def return_mic_source_label(self) -> str:
        source = self._return_mic_source_config()
        if not source:
            return "Off"
        if source == "micro":
            return "MICRO"
        return self.label_for_target(source, input_device=True) or "Off"

    def _return_mic_volume_state(self) -> tuple[int, bool]:
        channel = self._find_channel("return-mic")
        if channel is None:
            return 100, False

        try:
            volume = int(getattr(channel, "volume", 100))
        except Exception:
            volume = 100

        volume = max(0, min(180, volume))
        muted = bool(getattr(channel, "muted", False))
        return volume, muted

    def _apply_return_mic_visible_volume(self) -> None:
        volume, muted = self._return_mic_volume_state()
        mute_flag = "1" if muted else "0"

        for stream_id in self._sink_inputs_by_media_name("K-Sound-Hub-Return-Mic-Micro"):
            self._pactl("set-sink-input-volume", stream_id, f"{volume}%")
            self._pactl("set-sink-input-mute", stream_id, mute_flag)

    def _unload_return_mic_source_loopbacks(self) -> None:
        # Remove Return-Mic source-monitor loopbacks only.
        # Keep Soundboard -> MIC OUT untouched: source=soundboard.monitor -> retour.
        self._unload_modules_matching(
            lambda line: (
                "module-loopback" in line.lower()
                and "sink=retour" in line.lower()
                and "source=soundboard.monitor" not in line.lower()
                and (
                    "k-sound-hub-return-mic-micro" in line.lower()
                    or "source=micro" in line.lower()
                    or "source=alsa_input" in line.lower()
                )
            )
        )

    def _load_return_mic_micro_loopback(self, enabled: bool) -> None:
        self._unload_return_mic_source_loopbacks()

        source = self._return_mic_source_config() if enabled else ""
        if not source:
            return

        self._pactl(
            "load-module",
            "module-loopback",
            f"source={source}",
            "sink=retour",
            "latency_msec=20",
            "source_dont_move=true",
            "sink_dont_move=true",
            "channels=2",
            "sink_input_properties=media.name=K-Sound-Hub-Return-Mic-Micro",
        )

        time.sleep(0.06)
        self._apply_return_mic_visible_volume()

    def set_return_mic_source_label(self, label: str) -> bool:
        selected = str(label or "").strip()

        if not selected or selected.lower() == "off":
            target = ""
        elif selected.upper() == "MICRO":
            target = "micro"
        else:
            target = self.resolve_input_label(selected)

        data = self._read_settings_document()
        data["glass_return_mic_source"] = target
        data["glass_return_mic_micro_enabled"] = bool(target)
        self._write_settings_document(data)

        self._load_return_mic_micro_loopback(bool(target))
        self._apply_return_mic_visible_volume()
        QTimer.singleShot(120, self._apply_return_mic_visible_volume)

        self.status_changed.emit(f"MIC OUT source → {selected or 'Off'}")
        return True

    def return_mic_route_state(self) -> dict[str, bool]:
        enabled = bool(self._return_mic_source_config())
        return {
            "micro": enabled,
            "micro-final": enabled,
        }

    def set_return_mic_source_state(self, source_key: str, enabled: bool) -> bool:
        source = str(source_key or "").strip()
        if source == "micro-final":
            source = "micro"

        if not enabled:
            data = self._read_settings_document()
            data["glass_return_mic_source"] = ""
            data["glass_return_mic_micro_enabled"] = False
            self._write_settings_document(data)
            self._load_return_mic_micro_loopback(False)
            self.status_changed.emit("MIC OUT source → Off")
            return True

        data = self._read_settings_document()
        data["glass_return_mic_source"] = source
        data["glass_return_mic_micro_enabled"] = bool(source)
        self._write_settings_document(data)

        self._load_return_mic_micro_loopback(bool(source))
        self._apply_return_mic_visible_volume()
        QTimer.singleShot(120, self._apply_return_mic_visible_volume)

        self.status_changed.emit(f"MIC OUT source → {source or 'Off'}")
        return True

    def _sync_legacy_linked_channels_off(self) -> None:
        # Prevent the older channel engine from re-creating mixed routes.
        settings = self._read_settings_document()
        channels = settings.get("channels", [])
        if not isinstance(channels, list):
            return

        for channel in channels:
            if not isinstance(channel, dict):
                continue
            linked = [
                str(item).strip().lower()
                for item in channel.get("linked_channels", []) or []
                if str(item).strip().lower() not in {"soundboard", "micro", "micro-final"}
            ]
            channel["linked_channels"] = linked

        self._write_settings_document(settings)

    def micro_injection_channels(self) -> set[str]:
        data = self._read_settings_document()
        raw = data.get("glass_micro_injection_channels", [])
        if not isinstance(raw, list):
            raw = []
        allowed = {"all", "game", "chat", "media", "more"}
        return {str(item).strip().lower() for item in raw if str(item).strip().lower() in allowed}

    def set_micro_injection_channel_state(self, channel_key: str, enabled: bool) -> bool:
        key = str(channel_key or "").strip().lower()
        allowed = {"all", "game", "chat", "media", "more"}
        if key not in allowed:
            return False

        current = self.micro_injection_channels()
        if enabled:
            current.add(key)
        else:
            current.discard(key)

        data = self._read_settings_document()
        data["glass_micro_injection_channels"] = sorted(current)
        self._write_settings_document(data)

        # Immediate and stable: only add/remove the changed channel loopback state.
        self.apply_micro_injection_runtime_routes()
        self.status_changed.emit(f"MICRO injection {key.upper()}: {bool(enabled)}")
        return True

    def apply_micro_injection_runtime_routes(self) -> None:
        enabled = self.micro_injection_channels()
        allowed = {"all", "game", "chat", "media", "more"}

        existing: dict[str, str] = {}
        for line in self._pulse_modules():
            lowered = line.lower()
            parts = line.split("\t", 2)
            if not parts or not parts[0].isdigit():
                continue

            if "module-loopback" not in lowered or "sink=micro_bus" not in lowered:
                continue

            matched_key = ""
            for key in allowed:
                if f"k-sound-hub-micro-inject-{key}" in lowered or f"source={key}.monitor" in lowered:
                    matched_key = key
                    break

            if not matched_key:
                continue

            if matched_key in enabled and matched_key not in existing:
                existing[matched_key] = parts[0]
            else:
                self._pactl("unload-module", parts[0])

        for key in sorted(enabled):
            if key in existing:
                continue

            self._pactl(
                "load-module",
                "module-loopback",
                f"source={key}.monitor",
                "sink=micro_bus",
                "latency_msec=20",
                "source_dont_move=true",
                "sink_dont_move=true",
                "channels=2",
                f"sink_input_properties=media.name=K-Sound-Hub-Micro-Inject-{key}",
            )

    def apply_glass_runtime_routes(self) -> None:
        self._sync_legacy_linked_channels_off()
        self._ensure_glass_virtual_audio_buses()
        self._load_soundboard_output_loopback(self._soundboard_output_config())
        self._load_soundboard_micro_loopback(self._soundboard_send_to_micro_config())
        self._load_return_mic_micro_loopback(bool(self._return_mic_source_config()))
        self.apply_micro_injection_runtime_routes()
        self.normalize_channel_playback_routes()

    def _soundboard_route_state(self) -> dict[str, bool]:
        data = self._read_soundboard_document()
        output = self._normalize_soundboard_output_key(str(data.get("output_channel") or "media"))
        return {
            "send_to_micro": bool(data.get("send_to_micro", False)),
            "monitor_to_mic_out": output == "return-mic",
        }

    def _set_soundboard_route_state(self, route_key: str, enabled: bool) -> bool:
        route = str(route_key or "").strip().lower()

        if route == "monitor_to_mic_out":
            return self.set_soundboard_output_channel("return-mic" if enabled else "media")

        if route != "send_to_micro":
            return False

        data = self._read_soundboard_document()
        data["send_to_micro"] = bool(enabled)
        for slot in data.get("slots", []):
            if isinstance(slot, dict):
                slot["send_to_micro"] = bool(enabled)
        self._write_soundboard_document(data)

        self._sync_legacy_linked_channels_off()
        self._load_soundboard_micro_loopback(bool(enabled))
        self.status_changed.emit(f"Soundboard MICRO: {bool(enabled)}")
        return True

    def _sink_inputs_matching_tokens(self, tokens: list[str]) -> list[str]:
        result = self._pactl("list", "sink-inputs")
        if result.returncode != 0:
            return []

        wanted = [str(token or "").lower() for token in tokens if str(token or "").strip()]
        ids: list[str] = []
        current_id: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_id, current_lines
            if current_id is None:
                return
            block = "\n".join(current_lines).lower()
            if any(token in block for token in wanted):
                ids.append(current_id)
            current_id = None
            current_lines = []

        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            match = re.match(r"Sink Input #(\d+)", line)
            if match:
                flush()
                current_id = match.group(1)
                current_lines = [line]
            elif current_id is not None:
                current_lines.append(line)

        flush()
        return ids

    def _move_channel_playback_to_target(self, channel_key: str, target_sink: str) -> None:
        key = str(channel_key or "").strip().lower()
        target = str(target_sink or "").strip()
        if not key or key == "micro":
            return

        label = {
            "all": "ALL",
            "game": "GAME",
            "chat": "CHAT",
            "media": "MEDIA",
            "more": "MORE",
            "return-mic": "RETURN-MIC",
        }.get(key, key.upper())

        tokens = [
            f"ksh_{key}_eq.playback",
            f"K-Sound Hub {label} EQ",
            f"K-Sound Hub {label.replace('-', ' ')} EQ",
        ]

        stream_ids = self._sink_inputs_matching_tokens(tokens)
        if not stream_ids:
            return

        numeric_ids = sorted({int(stream_id) for stream_id in stream_ids})
        keep = str(numeric_ids[-1])

        for stream_id in numeric_ids[:-1]:
            self._pactl("kill-sink-input", str(stream_id))

        if target:
            self._pactl("move-sink-input", keep, target)

    def _persist_channel_primary_target(self, channel_key: str, target: str) -> None:
        data = self._read_settings_document()
        channels = data.get("channels", [])
        if not isinstance(channels, list):
            return

        for channel in channels:
            if isinstance(channel, dict) and channel.get("key") == channel_key:
                channel["primary_target"] = target
                break

        self._write_settings_document(data)

    def normalize_channel_playback_routes(self) -> None:
        for key in ("all", "game", "chat", "media", "more", "return-mic"):
            channel = self._find_channel(key)
            if channel is None:
                continue
            target = str(getattr(channel, "primary_target", "") or "").strip()
            self._move_channel_playback_to_target(key, target)

    def set_channel_primary_target(self, channel_key: str, target_sink: str) -> bool:
        key = str(channel_key or "").strip()
        target = str(target_sink or "").strip()

        channel = self._find_channel(key)
        if channel is None or not target:
            return False

        channel.primary_target = target

        try:
            self.audio_engine.apply_channel(self.settings, channel.key)
        except Exception as exc:
            self.status_changed.emit(f"Target route warning — {exc}")

        self._persist_channel_primary_target(channel.key, target)

        if channel.key != "micro":
            self._move_channel_playback_to_target(channel.key, target)

        if channel.key in {"micro", "return-mic"}:
            self._apply_return_mic_visible_volume()
            QTimer.singleShot(120, self._apply_return_mic_visible_volume)

        self._save_timer.start()

        if channel.key == "micro":
            label = self.label_for_target(target, input_device=True)
        else:
            label = self.label_for_target(target, input_device=False)

        self.status_changed.emit(f"{GLASS_CHANNEL_OVERLAY_META.get(channel.key, ('', channel.key.upper()))[1]} device → {label}")
        return True

    def channel_primary_target(self, channel_key: str) -> str:
        channel = self._find_channel(channel_key)
        if channel is None:
            return ""
        return str(getattr(channel, "primary_target", "") or "").strip()

    def set_soundboard_micro_enabled(self, enabled: bool) -> bool:
        data = self._read_soundboard_document()
        data["send_to_micro"] = bool(enabled)
        self._write_soundboard_document(data)
        self._load_soundboard_micro_loopback(bool(enabled))
        self.status_changed.emit(f"Soundboard MICRO → {bool(enabled)}")
        return True

    def soundboard_output_channel(self) -> str:
        return self._soundboard_output_config()

    def set_soundboard_output_channel(self, channel_key: str) -> bool:
        wanted = self._normalize_soundboard_output_key(channel_key)

        data = self._read_soundboard_document()
        data["output_channel"] = wanted
        data["monitor_to_mic_out"] = wanted == "return-mic"
        self._write_soundboard_document(data)

        self._sync_legacy_linked_channels_off()
        self._load_soundboard_output_loopback(wanted)

        label = SOUNDBOARD_LOGICAL_LABEL_BY_KEY.get(wanted, wanted.upper())
        self.status_changed.emit(f"Soundboard output → {label}")
        return True

    def _ensure_android_soundboard_dialog(self) -> SoundboardDialog:
        dialog = self._android_soundboard_dialog
        if dialog is None:
            dialog = SoundboardDialog(
                route_state_provider=self._soundboard_route_state,
                route_state_changed=self._set_soundboard_route_state,
            )
            dialog.hide()
            self._android_soundboard_dialog = dialog
        return dialog

    def _refresh_android_soundboard_slots(self, dialog: SoundboardDialog) -> None:
        try:
            dialog.slots = dialog._load_slots()
        except Exception:
            pass

    def _handle_soundboard_command(self, payload: dict, command: str) -> bool:
        command = str(command or "").strip().lower()
        if command not in {
            "soundboard",
            "soundboard-play",
            "soundboard_play",
            "soundboard-stop-all",
            "soundboard_stop_all",
            "soundboard-set-global-volume",
            "soundboard_set_global_volume",
            "soundboard-move-slot",
            "soundboard_move_slot",
            "soundboard-reorder-slots",
            "soundboard_reorder_slots",
        }:
            return False

        dialog = self._ensure_android_soundboard_dialog()

        if command in {"soundboard-stop-all", "soundboard_stop_all"}:
            dialog.stop_all()
            self.overlay_message_requested.emit("🎛 Soundboard stop all", False)
            self.status_changed.emit("Android remote: stop all")
            return True

        if command in {"soundboard-set-global-volume", "soundboard_set_global_volume"}:
            dialog.set_global_volume(payload.get("volume"))
            self.status_changed.emit(f"Android remote: global volume {payload.get('volume')}")
            return True

        if command in {"soundboard-move-slot", "soundboard_move_slot"}:
            slot = str(payload.get("slot") or payload.get("id") or payload.get("label") or "")
            direction = str(payload.get("direction") or "")
            self._refresh_android_soundboard_slots(dialog)
            ok = bool(dialog.move_slot_by_key(slot, direction))
            self.status_changed.emit(f"Android remote: move {slot} {direction} {'OK' if ok else 'failed'}")
            return True

        if command in {"soundboard-reorder-slots", "soundboard_reorder_slots"}:
            order = payload.get("order")
            self._refresh_android_soundboard_slots(dialog)
            ok = bool(dialog.reorder_slots_by_ids(order if isinstance(order, list) else []))
            self.status_changed.emit(f"Android remote: reorder {'OK' if ok else 'failed'}")
            return True

        if command in {"soundboard", "soundboard-play", "soundboard_play"}:
            slot = str(payload.get("slot") or payload.get("id") or payload.get("label") or "")
            self._refresh_android_soundboard_slots(dialog)
            ok = bool(dialog.play_slot_by_key(slot))
            if ok:
                self.overlay_message_requested.emit(f"🎛 Soundboard {slot}", False)
            self.status_changed.emit(f"Android remote: play {slot} {'OK' if ok else 'failed'}")
            return True

        return False


    def handle_ipc_message(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        command = str(payload.get("command", "")).strip().lower()
        if command and self._handle_soundboard_command(payload, command):
            return

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
            self.overlay_message_requested.emit(self._overlay_text(channel, "mute"), True)
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
        if hint in {"volume", "mute"}:
            self.overlay_message_requested.emit(
                self._overlay_text(channel, hint),
                bool(hint == "mute" and channel.muted),
            )

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

                if key in {"micro", "return-mic"}:
                    self._apply_return_mic_visible_volume()
                    QTimer.singleShot(120, self._apply_return_mic_visible_volume)
            except Exception as exc:
                self.status_changed.emit(f"Volume apply error on {key} — {exc}")

    def _flush_pending_channel_apply(self) -> None:
        keys = set(self._pending_apply_keys)
        self._pending_apply_keys.clear()

        for key in keys:
            try:
                self.audio_engine.apply_channel(self.settings, key)

                if key in {"micro", "return-mic"}:
                    self._apply_return_mic_visible_volume()
                    QTimer.singleShot(120, self._apply_return_mic_visible_volume)
            except Exception as exc:
                self.status_changed.emit(f"Channel apply error on {key} — {exc}")

    def _autosave(self) -> None:
        try:
            self.settings_store.save(self.settings)
        except Exception as exc:
            self.status_changed.emit(f"Settings save error — {exc}")


PHYSICAL_OUTPUT_TARGETS = [
    ("Arctis Nova Pro", "alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo"),
    ("USB / SPDIF", "alsa_output.usb-Generic_USB_Audio-00.HiFi__SPDIF__sink"),
    ("USB Speakers", "alsa_output.usb-Generic_USB_Audio-00.HiFi__Speaker__sink"),
    ("USB Headphones", "alsa_output.usb-Generic_USB_Audio-00.HiFi__Headphones__sink"),
]
PHYSICAL_OUTPUT_BY_LABEL = dict(PHYSICAL_OUTPUT_TARGETS)
PHYSICAL_OUTPUT_LABEL_BY_SINK = {sink: label for label, sink in PHYSICAL_OUTPUT_TARGETS}
PHYSICAL_OUTPUT_LABELS = [label for label, _sink in PHYSICAL_OUTPUT_TARGETS]

PHYSICAL_INPUT_TARGETS = [
    ("RØDE NT-USB", "alsa_input.usb-RODE_Microphones_RODE_NT-USB-00.iec958-stereo"),
    ("Arctis Mic", "alsa_input.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.mono-fallback"),
]
PHYSICAL_INPUT_BY_LABEL = dict(PHYSICAL_INPUT_TARGETS)
PHYSICAL_INPUT_LABEL_BY_SOURCE = {source: label for label, source in PHYSICAL_INPUT_TARGETS}

CHANNELS = [
    ("ALL", str(CHANNEL_ICON_PATHS["all"]), ["Arctis Nova Pro", "USB / SPDIF"], 76, "all"),
    ("GAME", str(CHANNEL_ICON_PATHS["game"]), ["Arctis Nova Pro", "USB / SPDIF"], 72, "game"),
    ("CHAT", str(CHANNEL_ICON_PATHS["chat"]), ["Arctis Nova Pro", "USB / SPDIF"], 70, "chat"),
    ("MEDIA", str(CHANNEL_ICON_PATHS["media"]), ["USB / SPDIF", "Arctis Nova Pro"], 64, "media"),
    ("MORE", str(CHANNEL_ICON_PATHS["more"]), ["Arctis Nova Pro", "USB / SPDIF"], 58, "more"),
    ("MICRO", str(CHANNEL_ICON_PATHS["micro"]), ["RØDE NT-USB", "Arctis Mic"], 84, "micro"),
    ("MIC OUT", str(CHANNEL_ICON_PATHS["return-mic"]), PHYSICAL_OUTPUT_LABELS, 52, "return-mic"),
]

APP_ROUTE_CHANNELS = [
    ("ALL", "all"),
    ("GAME", "game"),
    ("CHAT", "chat"),
    ("MEDIA", "media"),
    ("MORE", "more"),
]
APP_ROUTE_LABEL_BY_KEY = {key: label for label, key in APP_ROUTE_CHANNELS}
APP_ROUTE_KEY_BY_LABEL = {label: key for label, key in APP_ROUTE_CHANNELS}
APP_ROUTE_KEYS = {key for _label, key in APP_ROUTE_CHANNELS}

SOUNDBOARD_LOGICAL_OUTPUTS = [
    ("ALL", "all"),
    ("GAME", "game"),
    ("CHAT", "chat"),
    ("MEDIA", "media"),
    ("MORE", "more"),
    ("MIC OUT", "return-mic"),
]
SOUNDBOARD_LOGICAL_LABEL_BY_KEY = {key: label for label, key in SOUNDBOARD_LOGICAL_OUTPUTS}
SOUNDBOARD_LOGICAL_KEY_BY_LABEL = {label: key for label, key in SOUNDBOARD_LOGICAL_OUTPUTS}


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

QLabel#soundPadTrim {
    color: rgba(235, 248, 255, 220);
    font-size: 9px;
    font-weight: 780;
}

QCheckBox#soundboardAutoLevelToggle {
    color: rgba(235, 248, 255, 235);
    background: rgba(10, 22, 34, 185);
    border: 1px solid rgba(100, 190, 255, 75);
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 10px;
    font-weight: 780;
}
QCheckBox#soundboardAutoLevelToggle:hover {
    background: rgba(34, 82, 120, 195);
    border: 1px solid rgba(120, 210, 255, 130);
}
QCheckBox#soundboardAutoLevelToggle::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    margin-right: 7px;
}
QCheckBox#soundboardAutoLevelToggle::indicator:unchecked {
    background: rgba(0, 0, 0, 210);
    border: 1px solid rgba(235, 248, 255, 120);
}
QCheckBox#soundboardAutoLevelToggle::indicator:checked {
    background: rgba(78, 198, 255, 235);
    border: 1px solid rgba(210, 250, 255, 240);
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

QPushButton#selectButton[deviceMissing="true"] {
    color: rgba(255, 202, 120, 235);
    background: rgba(76, 42, 8, 150);
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


QFrame#soundPadCard[missingSound="true"] {
    border: 1px solid rgba(255, 182, 84, 190);
    background: rgba(75, 35, 18, 105);
}

QFrame#soundPadCard[missingSound="true"] QLabel#soundPadName {
    color: rgba(255, 224, 178, 245);
}

QFrame#soundPadCard[missingSound="true"] QLabel#soundPadMeta {
    color: rgba(255, 190, 96, 235);
    font-weight: 800;
}

QFrame#soundPadCard[missingSound="true"] QPushButton#soundPadEmoji {
    color: rgba(255, 201, 96, 245);
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






STYLE += """
/* Glass pad emoji + darkness slider only */
QPushButton#soundPadEmoji {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    background: rgba(0, 0, 0, 225);
    border: none;
    border-radius: 17px;
    padding: 0px;
    font-size: 20px;
}

QPushButton#soundPadEmoji:hover {
    background: rgba(34, 78, 108, 160);
    border-radius: 17px;
}

QFrame#emojiPalette {
    background: rgba(0, 0, 0, 225);
    border: 1px solid rgba(95, 190, 255, 55);
    border-radius: 18px;
}

QPushButton#emojiChoice {
    border-radius: 10px;
    background: rgba(18, 36, 54, 135);
}

QPushButton#emojiChoice:hover {
    border-radius: 10px;
    background: rgba(50, 120, 170, 175);
}

QFrame#padBgDarknessControls {
    background: rgba(0, 0, 0, 105);
    border: none;
    border-radius: 12px;
}

QSlider#padBgDarknessSlider::groove:horizontal {
    min-height: 6px;
    max-height: 6px;
    border-radius: 3px;
    background: rgba(0, 0, 0, 155);
}

QSlider#padBgDarknessSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0px;
    border-radius: 8px;
    background: rgba(110, 215, 255, 230);
}

QSlider#padBgDarknessSlider::sub-page:horizontal {
    border-radius: 3px;
    background: rgba(92, 204, 255, 145);
}

QSlider#padBgDarknessSlider::add-page:horizontal {
    border-radius: 3px;
    background: rgba(12, 24, 36, 150);
}
"""


STYLE += """
/* Glass soundboard volume slider */
QFrame#soundboardVolumeControls {
    background: rgba(0, 0, 0, 105);
    border: none;
    border-radius: 12px;
}

QLabel#soundboardVolumeLabel {
    color: rgba(215, 232, 246, 175);
    font-size: 10px;
    font-weight: 720;
}

QLabel#soundboardVolumeSign {
    color: rgba(215, 232, 246, 190);
    font-size: 12px;
    font-weight: 850;
    min-width: 10px;
    max-width: 10px;
    padding: 0px;
}

QSlider#soundboardVolumeSlider::groove:horizontal {
    min-height: 6px;
    max-height: 6px;
    border-radius: 3px;
    background: rgba(0, 0, 0, 155);
}

QSlider#soundboardVolumeSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0px;
    border-radius: 8px;
    background: rgba(110, 215, 255, 230);
}

QSlider#soundboardVolumeSlider::sub-page:horizontal {
    border-radius: 3px;
    background: rgba(92, 204, 255, 145);
}

QSlider#soundboardVolumeSlider::add-page:horizontal {
    border-radius: 3px;
    background: rgba(12, 24, 36, 150);
}

/* compact soundboard auto-level toggle v2 */
QCheckBox#soundboardAutoLevelToggle {
    padding: 2px 5px;
    min-height: 22px;
    max-height: 22px;
    border: none;
    background: transparent;
    font-size: 10px;
    font-weight: 760;
}

QCheckBox#soundboardAutoLevelToggle::indicator {
    width: 11px;
    height: 11px;
}

QPushButton#soundboardAnalyzeButton {
    padding: 0px;
    min-height: 28px;
    max-height: 28px;
    min-width: 30px;
    max-width: 30px;
    border: none;
    background: transparent;
    color: rgba(226, 242, 255, 235);
    font-size: 15px;
    font-weight: 760;
}

QPushButton#soundboardAnalyzeButton:hover {
    background: rgba(35, 82, 112, 90);
}

QPushButton#soundboardAnalyzeButton:disabled {
    color: rgba(185, 205, 220, 130);
    background: transparent;
}


/* Glass drawer/apps scrollbar */
QScrollArea#drawerScroll {
    border: none;
    background: transparent;
    padding-right: 0px;
}

QScrollBar#drawerScrollbar:vertical {
    background: rgba(0, 0, 0, 110);
    width: 8px;
    min-width: 8px;
    margin: 4px 1px 4px 3px;
    border: none;
    border-radius: 4px;
}

QScrollBar#drawerScrollbar::handle:vertical {
    background: rgba(92, 204, 255, 180);
    border: none;
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar#drawerScrollbar::handle:vertical:hover {
    background: rgba(115, 220, 255, 230);
}

QScrollBar#drawerScrollbar::add-line:vertical,
QScrollBar#drawerScrollbar::sub-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}

QScrollBar#drawerScrollbar::add-page:vertical,
QScrollBar#drawerScrollbar::sub-page:vertical {
    background: transparent;
    border: none;
}
"""

class AdaptiveScrollArea(QScrollArea):
    RIGHT_MARGIN_WITH_SCROLL = 14

    def __init__(self):
        super().__init__()
        self.setObjectName("drawerScroll")
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._applied_right_margin = -1
        self._pending_margin_update = False

        bar = self.verticalScrollBar()
        bar.setObjectName("drawerScrollbar")
        bar.setMinimumWidth(8)
        bar.setSingleStep(36)
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





    def _value_from_position(self, pos) -> int:
        minimum = int(self.minimum())
        maximum = int(self.maximum())
        span = max(1, maximum - minimum)

        if self.orientation() == Qt.Horizontal:
            usable = max(1, self.width() - 1)
            ratio = max(0.0, min(1.0, float(pos.x()) / float(usable)))
        else:
            usable = max(1, self.height() - 1)
            ratio = 1.0 - max(0.0, min(1.0, float(pos.y()) / float(usable)))

        return minimum + int(round(ratio * span))

    def _apply_pointer_value(self, event) -> None:
        value = self._value_from_position(event.position().toPoint())
        self.setSliderDown(True)
        if self.value() != value:
            self.setValue(value)
        try:
            self.sliderMoved.emit(value)
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._apply_pointer_value(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown() and event.buttons() & Qt.LeftButton:
            self._apply_pointer_value(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._apply_pointer_value(event)
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


DEVICE_NOT_FOUND_SUFFIX = " (not found)"
DEVICE_NOT_FOUND_PREFIX = "⚠ "


def _is_missing_device_label(label: str) -> bool:
    text = str(label or "").strip()
    return text.startswith(DEVICE_NOT_FOUND_PREFIX) and text.endswith(DEVICE_NOT_FOUND_SUFFIX)


def _format_missing_device_label(label: str) -> str:
    clean = str(label or "Unknown device").strip() or "Unknown device"
    if _is_missing_device_label(clean):
        return clean
    return f"{DEVICE_NOT_FOUND_PREFIX}{clean}{DEVICE_NOT_FOUND_SUFFIX}"


def _plain_missing_device_label(label: str) -> str:
    text = str(label or "").strip()
    if _is_missing_device_label(text):
        text = text[len(DEVICE_NOT_FOUND_PREFIX):]
        text = text[: -len(DEVICE_NOT_FOUND_SUFFIX)]
    return text.strip()


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
        missing = _is_missing_device_label(self._current)
        wanted_prop = "true" if missing else "false"
        if self.property("deviceMissing") != wanted_prop:
            self.setProperty("deviceMissing", wanted_prop)
            self.style().unpolish(self)
            self.style().polish(self)
        width = max(28, self.width() - 16)
        text = self.fontMetrics().elidedText(self._current, Qt.ElideRight, width)
        self.setText(text)
        self.setToolTip(_plain_missing_device_label(self._current) if missing else self._current)

    def _open_menu(self) -> None:
        if not self.items:
            return

        menu = QMenu(self)
        menu.setObjectName("compactSelectMenu")
        menu.setStyleSheet("""
QMenu#compactSelectMenu {
    background: rgba(0, 0, 0, 235);
    border: 1px solid rgba(90, 190, 255, 65);
    border-radius: 0px;
    padding: 3px;
}
QLabel#compactSelectItem {
    color: rgba(238, 246, 255, 235);
    background: transparent;
    padding: 5px 8px;
}
QLabel#compactSelectItem:hover {
    background: rgba(70, 165, 230, 80);
}
QLabel#compactSelectItemMissing {
    color: rgba(255, 202, 120, 235);
    background: rgba(76, 42, 8, 105);
    padding: 5px 8px;
}
""")

        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(str(item)) for item in self.items), default=self.width())
        wanted_width = max(self.width(), widest + 22, 118)
        wanted_width = min(wanted_width, 320)

        for item in self.items:
            label_text = str(item)
            missing = _is_missing_device_label(label_text)
            label = QLabel(label_text)
            label.setObjectName("compactSelectItemMissing" if missing else "compactSelectItem")
            label.setAlignment(Qt.AlignCenter)
            label.setFixedWidth(wanted_width - 6)
            label.setMinimumHeight(29)

            action = QWidgetAction(menu)
            action.setDefaultWidget(label)
            if missing:
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda _checked=False, value=item: self.set_current_text(value))
                label.mouseReleaseEvent = (
                    lambda event, item_action=action: (
                        item_action.trigger(),
                        menu.close(),
                        event.accept(),
                    )
                )
            menu.addAction(action)

        menu.setFixedWidth(wanted_width)

        button_bottom = self.mapToGlobal(self.rect().bottomLeft())
        button_top = self.mapToGlobal(self.rect().topLeft())
        button_center_x = self.mapToGlobal(self.rect().center()).x()

        pos = button_bottom
        pos.setX(button_center_x - wanted_width // 2)

        estimated_height = max(32, len(self.items) * 31 + 6)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()

            if pos.x() < available.left():
                pos.setX(available.left())
            if pos.x() + wanted_width > available.right():
                pos.setX(max(available.left(), available.right() - wanted_width))

            if pos.y() + estimated_height > available.bottom():
                pos.setY(max(available.top(), button_top.y() - estimated_height))
            if pos.y() < available.top():
                pos.setY(available.top())

        menu.exec(pos)





class LevelMeter(QWidget):
    # cached meter renderer v4
    # Same segmented look as v2, with soft attack + red/peak fixes.
    # Optimization: cache complete rendered frames per visual state so paintEvent
    # usually only does one drawPixmap instead of redrawing segments every frame.
    VISUAL_NOISE_FLOOR = 0.0012
    VISUAL_GAIN = 8.5
    VISUAL_GAMMA = 0.42
    PEAK_DECAY = 0.88
    PEAK_SILENCE_DECAY = 0.70
    PEAK_SILENCE_FLOOR = 0.006
    SEGMENTS = 16
    FRAME_CACHE_LIMIT = 96

    def __init__(self, level: float = 0.0, parent=None):
        super().__init__(parent)
        self.current = self._visual_level(level)
        self.target = self.current
        self.peak = self.current
        self._background_cache: QPixmap | None = None
        self._frame_cache: dict[tuple[int, int, bool], QPixmap] = {}
        self._cache_size: tuple[int, int] = (0, 0)
        self._segment_rects: list[QRectF] = []
        self._last_visual_state: tuple[int, int, bool] | None = None

        self._inactive_color = QColor(10, 22, 34, 118)
        self._peak_color = QColor(225, 250, 255, 220)
        self._silent_peak_color = QColor(150, 180, 200, 120)
        self._active_colors = (
            QColor(70, 210, 255, 165),
            QColor(90, 235, 145, 190),
            QColor(255, 178, 70, 205),
            QColor(255, 72, 92, 225),
        )

        self.setFixedWidth(10)
        self.setMinimumHeight(124)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _visual_level(self, level: float) -> float:
        try:
            raw = float(level)
        except Exception:
            raw = 0.0

        raw = max(0.0, min(1.0, raw))
        if raw <= self.VISUAL_NOISE_FLOOR:
            return 0.0

        normalized = (raw - self.VISUAL_NOISE_FLOOR) / max(0.000001, 1.0 - self.VISUAL_NOISE_FLOOR)
        boosted = max(0.0, min(1.0, normalized * self.VISUAL_GAIN))
        return max(0.0, min(1.0, boosted ** self.VISUAL_GAMMA))

    def _active_color_for_index(self, index: int) -> QColor:
        if index >= self.SEGMENTS - 1:
            return self._active_colors[3]
        if index >= int(self.SEGMENTS * 0.84):
            return self._active_colors[2]
        if index >= int(self.SEGMENTS * 0.68):
            return self._active_colors[1]
        return self._active_colors[0]

    def _ensure_cache(self) -> None:
        size = (self.width(), self.height())
        if self._background_cache is not None and self._cache_size == size:
            return

        self._cache_size = size
        self._segment_rects = []
        self._frame_cache.clear()

        pixmap = QPixmap(max(1, size[0]), max(1, size[1]))
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._inactive_color)

        width = max(2, self.width())
        height = max(2, self.height())
        gap = 2
        segment_h = max(2.0, (height - gap * (self.SEGMENTS - 1)) / max(1, self.SEGMENTS))
        bottom = height - 0.5

        for i in range(self.SEGMENTS):
            y = bottom - (i + 1) * segment_h - i * gap
            rect = QRectF(0.5, y, width - 1.0, segment_h)
            self._segment_rects.append(rect)
            painter.drawRoundedRect(rect, 1.5, 1.5)

        painter.end()
        self._background_cache = pixmap
        self._last_visual_state = None

    def _frame_for_state(self, state: tuple[int, int, bool]) -> QPixmap:
        self._ensure_cache()

        cached = self._frame_cache.get(state)
        if cached is not None:
            return cached

        if len(self._frame_cache) > self.FRAME_CACHE_LIMIT:
            self._frame_cache.clear()

        active, peak_index, silent = state
        size = (max(1, self.width()), max(1, self.height()))

        pixmap = QPixmap(size[0], size[1])
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(Qt.NoPen)

        if self._background_cache is not None:
            painter.drawPixmap(0, 0, self._background_cache)

        for i in range(min(active, len(self._segment_rects))):
            painter.setBrush(self._active_color_for_index(i))
            painter.drawRoundedRect(self._segment_rects[i], 1.5, 1.5)

        if self._segment_rects:
            if silent:
                peak_y = self._segment_rects[0].bottom() - 1.0
                peak_color = self._silent_peak_color
            else:
                peak_index = max(0, min(len(self._segment_rects) - 1, peak_index))
                peak_y = self._segment_rects[peak_index].top()
                peak_color = self._peak_color

            painter.setBrush(peak_color)
            painter.drawRect(QRectF(0.0, peak_y, float(self.width()), 2.0))

        painter.end()

        self._frame_cache[state] = pixmap
        return pixmap

    def resizeEvent(self, event) -> None:
        self._background_cache = None
        self._frame_cache.clear()
        self._last_visual_state = None
        super().resizeEvent(event)

    def set_level(self, level: float) -> None:
        self.target = self._visual_level(level)
        if self.target > self.peak:
            self.peak = self.target

    def _visual_state(self) -> tuple[int, int, bool]:
        # Keep the original color zones, but allow real top-level peaks to
        # light the last segment even with softened attack smoothing.
        # Without this, short loud peaks can be smoothed just below segment 16.
        level_for_active = self.current

        # The last red segment is a "top / clip proximity" indicator.
        # With soft attack enabled, short loud peaks may never push `current`
        # high enough before the target falls again. When the target/peak is
        # already in the top visual zone, force only the active-count input to
        # full scale so the 16th segment can light without changing colors or
        # the actual meter backend.
        top_trigger = (self.SEGMENTS - 2) / max(1, self.SEGMENTS)  # 14/16 = 0.875
        if self.target >= top_trigger or self.peak >= top_trigger:
            level_for_active = 1.0

        active = int(math.ceil(level_for_active * self.SEGMENTS)) if level_for_active > 0.0 else 0
        active = max(0, min(self.SEGMENTS, active))

        silent = self.peak <= self.PEAK_SILENCE_FLOOR and self.current <= self.PEAK_SILENCE_FLOOR
        if silent:
            peak_index = -1
        elif active >= self.SEGMENTS:
            # If the top red segment is lit by the top-zone trigger, the peak
            # marker must follow it too. Otherwise the 16th segment lights but
            # the small peak line remains one or two segments lower.
            peak_index = self.SEGMENTS - 1
        else:
            peak_index = max(0, min(self.SEGMENTS - 1, int(math.ceil(self.peak * self.SEGMENTS)) - 1))

        return active, peak_index, silent

    def tick(self) -> None:
        # Soft attack: keeps the original segmented/cache renderer,
        # but avoids jumping too hard upward.
        if self.target > self.current:
            self.current = self.current * 0.55 + self.target * 0.45
        else:
            self.current = self.current * 0.80 + self.target * 0.20

        if self.target <= 0.0 and self.current < self.PEAK_SILENCE_FLOOR:
            self.current = 0.0

        if self.target <= 0.0 and self.current <= 0.0:
            self.peak *= self.PEAK_SILENCE_DECAY
        else:
            self.peak = max(self.current, self.peak * self.PEAK_DECAY)

        if self.target <= 0.0 and self.current < self.PEAK_SILENCE_FLOOR and self.peak < self.PEAK_SILENCE_FLOOR:
            self.peak = 0.0

        state = self._visual_state()
        if state != self._last_visual_state:
            self.update()

    def paintEvent(self, event) -> None:
        state = self._visual_state()
        self._last_visual_state = state

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.drawPixmap(0, 0, self._frame_for_state(state))



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

        title = QLabel("K-Sounds Hub")
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
        device_callback=None,
        current_device: str | None = None,
    ):
        super().__init__()
        self.channel_key = str(channel_key or "").strip()
        self._volume_callback = volume_callback
        self._mute_callback = mute_callback
        self._device_callback = device_callback
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

        icon_label = QLabel()
        icon_label.setObjectName("channelIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        self._set_icon(icon_label, icon)
        root.addWidget(icon_label, 0, Qt.AlignHCenter)

        name_label = QLabel(name)
        name_label.setObjectName("channelName")
        name_label.setAlignment(Qt.AlignCenter)
        root.addWidget(name_label)

        self.device_select = SelectButton(devices, current_device or (devices[0] if devices else ""), self._device_changed)
        self.device_select.setMinimumWidth(0)
        self.device_select.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.device_select)

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

    def _set_icon(self, icon_label: QLabel, icon: str) -> None:
        icon_path = Path(str(icon or ""))
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                icon_label.setFixedSize(48, 48)
                return
        icon_label.setText(str(icon or ""))
        icon_label.setFixedSize(48, 48)

    def set_meters_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.left_meter.setVisible(visible)
        self.right_meter.setVisible(visible)

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

    def _device_changed(self, label: str) -> None:
        if getattr(self, "_syncing_controls", False):
            return
        if self._device_callback is not None:
            self._device_callback(self.channel_key, str(label or "").strip())

    def sync_device_choices(self, devices: list[str], current_device: str | None = None) -> None:
        items = [str(item or "").strip() for item in (devices or []) if str(item or "").strip()]
        current = str(current_device or "").strip()
        if current and current not in items:
            items.insert(0, current)
        if not current and items:
            current = items[0]

        self._syncing_controls = True
        try:
            self.device_select.items = items
            self.device_select._current = current
            self.device_select._sync_text()
        finally:
            self._syncing_controls = False

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
    def __init__(self, stream, move_callback):
        super().__init__()
        self.stream = stream
        self.stream_id = int(getattr(stream, "stream_id", -1))
        self._move_callback = move_callback
        self._moving = False

        self.setObjectName("appsRouteCard")
        self.setMinimumHeight(66)

        root = QHBoxLayout(self)
        root.setContentsMargins(9, 8, 9, 8)
        root.setSpacing(8)

        icon_label = QLabel(self._icon_for_stream(stream))
        icon_label.setObjectName("appRouteIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        name_label = QLabel(self._stream_name(stream))
        name_label.setObjectName("appRouteName")
        name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        name_label.setToolTip(self._tooltip_for_stream(stream))
        text_col.addWidget(name_label)

        self.meta_label = QLabel(self._stream_meta(stream))
        self.meta_label.setObjectName("appRouteMeta")
        self.meta_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.meta_label.setToolTip(self._tooltip_for_stream(stream))
        text_col.addWidget(self.meta_label)

        root.addLayout(text_col, 1)

        arrow = QLabel("→")
        arrow.setObjectName("appRouteArrow")
        arrow.setAlignment(Qt.AlignCenter)
        root.addWidget(arrow)

        current_key = str(getattr(stream, "sink_name", "") or "").strip()
        current_label = APP_ROUTE_LABEL_BY_KEY.get(current_key, "ALL")
        self.select = SelectButton([label for label, _key in APP_ROUTE_CHANNELS], current_label, self._channel_changed)
        self.select.setMinimumWidth(70)
        self.select.setMaximumWidth(82)
        root.addWidget(self.select)

    def _stream_name(self, stream) -> str:
        return str(getattr(stream, "display_name", "") or f"Stream {getattr(stream, 'stream_id', '?')}")

    def _stream_meta(self, stream) -> str:
        parts = [f"#{getattr(stream, 'stream_id', '?')}"]
        sink = str(getattr(stream, "sink_name", "") or "").strip()
        parts.append(f"now: {APP_ROUTE_LABEL_BY_KEY.get(sink, sink or 'unknown')}")

        binary_name = str(getattr(stream, "binary_name", "") or "").strip()
        app_name = str(getattr(stream, "app_name", "") or "").strip()
        media_name = str(getattr(stream, "media_name", "") or "").strip()

        if binary_name:
            parts.append(f"bin: {binary_name}")
        elif app_name:
            parts.append(app_name)
        elif media_name:
            parts.append(media_name)

        return " · ".join(parts)

    def _tooltip_for_stream(self, stream) -> str:
        values = [
            ("stream", getattr(stream, "stream_id", "")),
            ("sink", getattr(stream, "sink_name", "")),
            ("display", getattr(stream, "display_name", "")),
            ("app", getattr(stream, "app_name", "")),
            ("bin", getattr(stream, "binary_name", "")),
            ("media", getattr(stream, "media_name", "")),
            ("node", getattr(stream, "node_name", "")),
        ]
        return "\n".join(f"{key}: {value}" for key, value in values if str(value or "").strip())

    def _icon_for_stream(self, stream) -> str:
        haystack = " ".join(
            str(value or "").lower()
            for value in (
                getattr(stream, "display_name", ""),
                getattr(stream, "app_name", ""),
                getattr(stream, "binary_name", ""),
                getattr(stream, "media_name", ""),
                getattr(stream, "node_name", ""),
            )
        )

        if any(word in haystack for word in ("steam", "game", "proton", "wine")):
            return "🎮"
        if any(word in haystack for word in ("firefox", "chrome", "browser", "youtube")):
            return "🌐"
        if any(word in haystack for word in ("discord", "vesktop", "chat")):
            return "💬"
        if any(word in haystack for word in ("spotify", "music", "vlc", "media")):
            return "🎵"
        if "soundboard" in haystack:
            return "🎛"
        return "▣"

    def _channel_changed(self, label: str) -> None:
        if self._moving:
            return

        target = APP_ROUTE_KEY_BY_LABEL.get(str(label or "").strip())
        if not target:
            return

        if target == str(getattr(self.stream, "sink_name", "") or "").strip():
            return

        self._moving = True
        self.select.setEnabled(False)
        self.meta_label.setText(f"Moving to {label}…")

        ok = False
        if self._move_callback is not None:
            ok = bool(self._move_callback(self.stream_id, target))

        if not ok:
            self.meta_label.setText("Move failed")
            self.select.setToolTip("PipeWire refused the move, or the stream disappeared.")
        else:
            self.meta_label.setText(f"Moved to {label}")

        QTimer.singleShot(350, self._unlock_after_move)

    def _unlock_after_move(self) -> None:
        self._moving = False
        self.select.setEnabled(True)



class PermanentRouteCard(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        meta: str,
        *,
        checks: list[tuple[str, bool, object]] | None = None,
        select_items: list[str] | None = None,
        select_current: str | None = None,
        select_callback=None,
    ):
        super().__init__()
        self.setObjectName("appsRouteCard")
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        root = QVBoxLayout(self)
        root.setContentsMargins(9, 8, 9, 8)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("appRouteIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        header.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        name_label = QLabel(title)
        name_label.setObjectName("appRouteName")
        text_col.addWidget(name_label)

        meta_label = QLabel(meta)
        meta_label.setObjectName("appRouteMeta")
        meta_label.setWordWrap(True)
        text_col.addWidget(meta_label)

        header.addLayout(text_col, 1)
        root.addLayout(header)

        if select_items:
            select_row = QHBoxLayout()
            select_row.setContentsMargins(0, 0, 0, 0)
            select_row.setSpacing(8)

            label = QLabel("Output")
            label.setObjectName("appRouteMeta")
            select_row.addWidget(label)

            self.select = SelectButton(select_items, select_current or select_items[0], select_callback)
            self.select.setMinimumWidth(150)
            select_row.addWidget(self.select, 1)
            root.addLayout(select_row)

        if checks:
            checks_grid = QGridLayout()
            checks_grid.setContentsMargins(0, 0, 0, 0)
            checks_grid.setHorizontalSpacing(10)
            checks_grid.setVerticalSpacing(6)

            for index, (label, checked, callback) in enumerate(checks):
                box = QCheckBox(label)
                box.setObjectName("routeCheck")
                box.setMinimumWidth(82)
                box.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
                box.setChecked(bool(checked))
                box.toggled.connect(lambda value, cb=callback: cb(bool(value)) if cb is not None else None)
                checks_grid.addWidget(box, index // 2, index % 2)

            self.setMinimumHeight(max(self.minimumHeight(), 132 if len(checks) > 2 else 78))
            root.addLayout(checks_grid)



class AppsPanel(QWidget):
    def __init__(self, backend_controller=None):
        super().__init__()
        self.backend_controller = backend_controller
        self._last_signature: tuple = ()
        self._permanent_routes_signature: tuple = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        hint = QLabel("Active playback streams")
        hint.setObjectName("muted")
        top.addWidget(hint, 1)

        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("padTopButton")
        refresh_btn.setToolTip("Refresh streams")
        refresh_btn.setFixedWidth(34)
        refresh_btn.clicked.connect(lambda: self.refresh_streams(force=True))
        top.addWidget(refresh_btn)

        root.addLayout(top)

        self.permanent_host = QWidget()
        self.permanent_layout = QVBoxLayout(self.permanent_host)
        self.permanent_layout.setContentsMargins(0, 0, 0, 0)
        self.permanent_layout.setSpacing(9)
        root.addWidget(self.permanent_host)

        self._build_permanent_routes()
        if self.backend_controller is not None and hasattr(self.backend_controller, "apply_glass_runtime_routes"):
            self.backend_controller.apply_glass_runtime_routes()

        self.streams_host = QWidget()
        self.streams_layout = QVBoxLayout(self.streams_host)
        self.streams_layout.setContentsMargins(0, 0, 0, 0)
        self.streams_layout.setSpacing(9)
        root.addWidget(self.streams_host)

        root.addStretch(1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1400)
        self.refresh_timer.timeout.connect(self.refresh_streams)
        self.refresh_timer.start()

        self.refresh_streams(force=True)

    def _clear_permanent_routes(self) -> None:
        while self.permanent_layout.count():
            item = self.permanent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _permanent_routes_current_signature(self) -> tuple:
        if self.backend_controller is None:
            return ()
        return_pairs = tuple(self.backend_controller.available_input_targets())
        return_source = ""
        if hasattr(self.backend_controller, "_return_mic_source_config"):
            return_source = str(self.backend_controller._return_mic_source_config() or "").strip()
        soundboard_state = self.backend_controller._soundboard_route_state()
        injected = tuple(sorted(self.backend_controller.micro_injection_channels()))
        return (
            return_pairs,
            return_source,
            self.backend_controller.soundboard_output_channel(),
            bool(soundboard_state.get("send_to_micro")),
            injected,
        )

    def _refresh_permanent_routes_if_needed(self, force: bool = False) -> None:
        try:
            signature = self._permanent_routes_current_signature()
        except Exception as exc:
            if self.backend_controller is not None:
                self.backend_controller.status_changed.emit(f"Device watcher error — {exc}")
            return
        if not force and signature == self._permanent_routes_signature:
            return
        self._permanent_routes_signature = signature
        self._build_permanent_routes()

    def _build_permanent_routes(self) -> None:
        self._clear_permanent_routes()

        if self.backend_controller is None:
            self.permanent_layout.addWidget(PermanentRouteCard("⚠", "Internal routes", "Backend not connected yet"))
            return

        soundboard_state = self.backend_controller._soundboard_route_state()

        current_key = self.backend_controller.soundboard_output_channel()
        current_label = SOUNDBOARD_LOGICAL_LABEL_BY_KEY.get(current_key, "MEDIA")

        self.permanent_layout.addWidget(
            PermanentRouteCard(
                "🎛",
                "Soundboard",
                "Choose where you hear the soundboard. MICRO injects it into your microphone.",
                select_items=[label for label, _key in SOUNDBOARD_LOGICAL_OUTPUTS],
                select_current=current_label,
                select_callback=self._set_soundboard_output,
                checks=[
                    ("MICRO", bool(soundboard_state.get("send_to_micro")), self._set_soundboard_to_micro),
                ],
            )
        )

        return_pairs = self.backend_controller.available_input_targets()
        return_inputs = ["Off"] + [label for label, _source in return_pairs]
        current_return = self.backend_controller.return_mic_source_label()
        current_return_source = ""
        if hasattr(self.backend_controller, "_return_mic_source_config"):
            current_return_source = str(self.backend_controller._return_mic_source_config() or "").strip()
        if current_return_source and current_return_source != "micro" and not any(source == current_return_source for _label, source in return_pairs):
            current_return = _format_missing_device_label(current_return or current_return_source)
            if current_return not in return_inputs:
                return_inputs.insert(1, current_return)
        elif current_return not in return_inputs:
            current_return = "Off"

        self.permanent_layout.addWidget(
            PermanentRouteCard(
                "🎧",
                "MIC OUT / Return Mic",
                "Choose the microphone source you hear in the return channel.",
                select_items=return_inputs,
                select_current=current_return,
                select_callback=self._set_return_mic_source,
            )
        )

        injected = self.backend_controller.micro_injection_channels()
        injection_checks = [
            ("ALL", "all" in injected, lambda value, key="all": self._set_micro_injection_channel(key, value)),
            ("GAME", "game" in injected, lambda value, key="game": self._set_micro_injection_channel(key, value)),
            ("CHAT", "chat" in injected, lambda value, key="chat": self._set_micro_injection_channel(key, value)),
            ("MEDIA", "media" in injected, lambda value, key="media": self._set_micro_injection_channel(key, value)),
            ("MORE", "more" in injected, lambda value, key="more": self._set_micro_injection_channel(key, value)),
        ]

        self.permanent_layout.addWidget(
            PermanentRouteCard(
                "🎙",
                "MICRO Injection",
                "Send selected channels into the MICRO output.",
                checks=injection_checks,
            )
        )

    def _set_soundboard_output(self, label: str) -> None:
        if self.backend_controller is None:
            return
        key = SOUNDBOARD_LOGICAL_KEY_BY_LABEL.get(str(label or "").strip())
        if not key:
            return
        self.backend_controller.set_soundboard_output_channel(key)
        self._build_permanent_routes()

    def _set_soundboard_to_mic_out(self, enabled: bool) -> None:
        if self.backend_controller is None:
            return
        self.backend_controller.set_soundboard_output_channel("return-mic" if enabled else "media")
        QTimer.singleShot(120, self._build_permanent_routes)

    def _set_soundboard_to_micro(self, enabled: bool) -> None:
        if self.backend_controller is None:
            return
        self.backend_controller.set_soundboard_micro_enabled(bool(enabled))
        QTimer.singleShot(80, self._build_permanent_routes)

    def _set_return_mic_source(self, label: str) -> None:
        if self.backend_controller is None:
            return
        selected = str(label or "").strip()
        if _is_missing_device_label(selected):
            self.backend_controller.status_changed.emit(f"Device not found: {_plain_missing_device_label(selected)}")
            return
        self.backend_controller.set_return_mic_source_label(selected)
        self._build_permanent_routes()

    def _set_return_mic_micro_source(self, enabled: bool) -> None:
        # Compatibility with older checkbox path. The UI now uses _set_return_mic_source().
        if self.backend_controller is None:
            return
        if enabled:
            self.backend_controller.set_return_mic_source_label("MICRO")
        else:
            self.backend_controller.set_return_mic_source_label("Off")
        self._build_permanent_routes()

    def _set_return_mic_output(self, label: str) -> None:
        if self.backend_controller is None:
            return
        sink = PHYSICAL_OUTPUT_BY_LABEL.get(str(label or "").strip())
        if not sink:
            return
        self.backend_controller.set_channel_primary_target("return-mic", sink)

    def _set_micro_injection_channel(self, channel_key: str, enabled: bool) -> None:
        if self.backend_controller is None:
            return
        self.backend_controller.set_micro_injection_channel_state(channel_key, bool(enabled))
        self._build_permanent_routes()

    def _clear_streams(self) -> None:
        while self.streams_layout.count():
            item = self.streams_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _is_internal_soundboard_stream(self, stream) -> bool:
        sink_name = str(getattr(stream, "sink_name", "") or "").strip().lower()
        values = [
            getattr(stream, "display_name", ""),
            getattr(stream, "app_name", ""),
            getattr(stream, "binary_name", ""),
            getattr(stream, "media_name", ""),
            getattr(stream, "node_name", ""),
            sink_name,
        ]
        haystack = " ".join(str(value or "").lower() for value in values)

        internal_tokens = [
            "ksh_keepalive",
            "ksh_mic_physical",
            "k-sound-hub-soundboard-to-output",
            "k-sound-hub-soundboard-to-micro",
            "k-sound-hub-return-mic-micro",
            "k-sounds hub mic output monitor",
            "k-sound hub all eq",
            "k-sound hub game eq",
            "k-sound hub chat eq",
            "k-sound hub media eq",
            "k-sound hub more eq",
            "k-sound hub return-mic eq",
            "k-sound-hub-soundboard",
            "k-sounds hub soundboard",
        ]

        if any(token in haystack for token in internal_tokens):
            return True
        if sink_name == "soundboard":
            return True
        if "soundboard" in haystack and any(token in haystack for token in ("pacat", "python", "k-sounds", "k-sound")):
            return True
        if "return-mic-micro" in haystack:
            return True
        return False

    def _stream_signature(self, streams: list) -> tuple:
        return tuple(
            (
                int(getattr(stream, "stream_id", -1)),
                str(getattr(stream, "display_name", "") or ""),
                str(getattr(stream, "sink_name", "") or ""),
                str(getattr(stream, "app_name", "") or ""),
                str(getattr(stream, "binary_name", "") or ""),
                str(getattr(stream, "media_name", "") or ""),
                str(getattr(stream, "node_name", "") or ""),
            )
            for stream in streams
        )

    def refresh_streams(self, force: bool = False) -> None:
        if self.backend_controller is None:
            self._show_message("Backend not connected yet")
            return

        self._refresh_permanent_routes_if_needed(force=force)

        streams = self.backend_controller.list_app_streams()
        visible_streams = [
            stream for stream in streams
            if not self._is_internal_soundboard_stream(stream)
        ]

        signature = self._stream_signature(visible_streams)
        if not force and signature == self._last_signature:
            return

        self._last_signature = signature
        self._clear_streams()

        if not visible_streams:
            self._show_message("No active external playback app stream")
            return

        for stream in visible_streams:
            self.streams_layout.addWidget(AppRouteCard(stream, self._move_stream))

    def _show_message(self, text: str) -> None:
        self._clear_streams()
        label = QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        self.streams_layout.addWidget(label)

    def _move_stream(self, stream_id: int, channel_key: str) -> bool:
        if self.backend_controller is None:
            return False

        ok = bool(self.backend_controller.move_app_stream(stream_id, channel_key))
        QTimer.singleShot(150, lambda: self.refresh_streams(force=True))
        return ok




class EqPanel(QWidget):
    CHANNELS = [
        ("ALL", "all"),
        ("GAME", "game"),
        ("CHAT", "chat"),
        ("MEDIA", "media"),
        ("MORE", "more"),
    ]

    def __init__(self, backend_controller=None):
        super().__init__()
        self.backend_controller = backend_controller
        self._channel_label_by_key = {key: label for label, key in self.CHANNELS}
        self._channel_key_by_label = {label: key for label, key in self.CHANNELS}
        self._syncing = False
        self._pending_band_index: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(QLabel("Channel"))
        self.eq_channel_select = SelectButton(
            [label for label, _key in self.CHANNELS],
            "GAME",
            self._eq_channel_changed,
        )
        root.addWidget(self.eq_channel_select)

        root.addWidget(QLabel("Preset"))
        self.eq_preset_select = SelectButton(["Default"], "Default", self._eq_preset_changed)
        root.addWidget(self.eq_preset_select)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        self.new_button = QPushButton("New")
        self.new_button.setObjectName("padTopButton")
        self.new_button.clicked.connect(self._create_preset)
        actions.addWidget(self.new_button)

        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.setObjectName("padTopButton")
        self.duplicate_button.clicked.connect(self._duplicate_preset)
        actions.addWidget(self.duplicate_button)

        self.rename_button = QPushButton("Rename")
        self.rename_button.setObjectName("padTopButton")
        self.rename_button.clicked.connect(self._rename_preset)
        actions.addWidget(self.rename_button)

        self.delete_button = QPushButton("🗑")
        self.delete_button.setObjectName("padDeleteButton")
        self.delete_button.setToolTip("Delete EQ preset")
        self.delete_button.setFixedWidth(34)
        self.delete_button.clicked.connect(self._delete_preset)
        actions.addWidget(self.delete_button)

        root.addLayout(actions)

        self.bands_card = QFrame()
        self.bands_card.setObjectName("channelCard")
        self.bands_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        bands_layout = QHBoxLayout(self.bands_card)
        bands_layout.setContentsMargins(7, 8, 7, 8)
        bands_layout.setSpacing(3)

        self.band_controls: list[tuple[QLabel, NoWheelSlider, QLabel]] = []
        for index in range(10):
            col = QVBoxLayout()
            col.setSpacing(3)

            gain_label = QLabel("+0.0")
            gain_label.setObjectName("muted")
            gain_label.setAlignment(Qt.AlignCenter)
            col.addWidget(gain_label)

            slider = NoWheelSlider(Qt.Vertical)
            slider.setRange(-24, 24)
            slider.setValue(0)
            slider.setMinimumHeight(118)
            slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            slider.setTracking(False)
            slider.sliderMoved.connect(lambda raw, idx=index: self._preview_band_label(idx, raw))
            slider.valueChanged.connect(lambda raw, idx=index: self._eq_band_changed(idx, raw))
            col.addWidget(slider, 1, Qt.AlignHCenter)

            freq_label = QLabel("—")
            freq_label.setObjectName("muted")
            freq_label.setAlignment(Qt.AlignCenter)
            col.addWidget(freq_label)

            self.band_controls.append((gain_label, slider, freq_label))
            bands_layout.addLayout(col)

        root.addWidget(self.bands_card, 1)

        self.status_label = QLabel("EQ changes apply live and are saved automatically.")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(120)
        self.apply_timer.timeout.connect(self._apply_pending_band)

        self._reload_profiles()

    def _current_channel_key(self) -> str:
        return self._channel_key_by_label.get(self.eq_channel_select.current_text(), "game")

    def _current_profile_name(self) -> str:
        return str(self.eq_preset_select.current_text() or "").strip()

    def _set_select_items(self, select: SelectButton, items: list[str], current: str) -> None:
        select.items = list(items) if items else ["Default"]
        select._current = current if current in select.items else select.items[0]
        select._sync_text()

    def _ask_name(self, title: str, label: str, default: str) -> str:
        value, ok = QInputDialog.getText(self, title, label, text=str(default or ""))
        if not ok:
            return ""
        return str(value or "").strip()

    def _format_frequency(self, frequency: float) -> str:
        try:
            value = float(frequency)
        except Exception:
            return "—"
        if value >= 1000:
            return f"{value / 1000:g}k"
        return f"{int(value)}"

    def _format_gain(self, gain_db: float) -> str:
        try:
            value = round(float(gain_db) * 2.0) / 2.0
        except Exception:
            value = 0.0
        return f"{value:+.1f}"

    def _raw_to_gain(self, raw: int) -> float:
        return round(float(raw) / 2.0, 1)

    def _gain_to_raw(self, gain_db: float) -> int:
        try:
            return int(round(float(gain_db) * 2.0))
        except Exception:
            return 0

    def _reload_profiles(self, preferred: str | None = None) -> None:
        if self.backend_controller is None:
            self.status_label.setText("EQ backend not connected yet.")
            return

        channel_key = self._current_channel_key()
        names, selected = self.backend_controller.eq_profile_names(channel_key)
        if preferred and preferred in names:
            selected = preferred

        self._syncing = True
        self._set_select_items(self.eq_preset_select, names or ["Default"], selected or (names[0] if names else "Default"))
        self._syncing = False

        self._reload_bands()

    def _reload_bands(self) -> None:
        if self.backend_controller is None:
            return

        channel_key = self._current_channel_key()
        profile_name = self._current_profile_name()
        bands = self.backend_controller.eq_profile_bands(channel_key, profile_name)

        self._syncing = True
        for index, (gain_label, slider, freq_label) in enumerate(self.band_controls):
            if index < len(bands):
                frequency, gain_db, _q = bands[index]
                raw = self._gain_to_raw(gain_db)
                slider.setEnabled(True)
                slider.setValue(max(slider.minimum(), min(slider.maximum(), raw)))
                gain_label.setText(self._format_gain(self._raw_to_gain(slider.value())))
                freq_label.setText(self._format_frequency(frequency))
            else:
                slider.setEnabled(False)
                slider.setValue(0)
                gain_label.setText("—")
                freq_label.setText("—")
        self._syncing = False

        label = self._channel_label_by_key.get(channel_key, channel_key.upper())
        self.status_label.setText(f"{label} · {profile_name or 'Default'} · live EQ")

    def _eq_channel_changed(self, channel_label: str) -> None:
        if self._syncing:
            return
        self._reload_profiles()

    def _eq_preset_changed(self, preset: str) -> None:
        if self._syncing or self.backend_controller is None:
            return

        channel_key = self._current_channel_key()
        if self.backend_controller.select_eq_profile(channel_key, preset):
            self._reload_bands()
        else:
            self.status_label.setText("Could not apply EQ preset.")

    def _create_preset(self) -> None:
        if self.backend_controller is None:
            return

        name = self._ask_name("New EQ preset", "Preset name:", "New preset")
        if not name:
            return

        created = self.backend_controller.create_eq_profile(self._current_channel_key(), name)
        if created:
            self._reload_profiles(preferred=created)
            self.status_label.setText(f"Created preset: {created}")
        else:
            self.status_label.setText("Could not create EQ preset.")

    def _duplicate_preset(self) -> None:
        if self.backend_controller is None:
            return

        current = self._current_profile_name()
        name = self._ask_name("Duplicate EQ preset", "New preset name:", f"{current} copy")
        if not name:
            return

        created = self.backend_controller.duplicate_eq_profile(self._current_channel_key(), current, name)
        if created:
            self._reload_profiles(preferred=created)
            self.status_label.setText(f"Duplicated preset: {created}")
        else:
            self.status_label.setText("Could not duplicate EQ preset.")

    def _rename_preset(self) -> None:
        if self.backend_controller is None:
            return

        current = self._current_profile_name()
        name = self._ask_name("Rename EQ preset", "New preset name:", current)
        if not name:
            return

        renamed = self.backend_controller.rename_eq_profile(self._current_channel_key(), current, name)
        if renamed:
            self._reload_profiles(preferred=renamed)
            self.status_label.setText(f"Renamed preset: {renamed}")
        else:
            self.status_label.setText("Could not rename EQ preset.")

    def _delete_preset(self) -> None:
        if self.backend_controller is None:
            return

        current = self._current_profile_name()
        names, _selected = self.backend_controller.eq_profile_names(self._current_channel_key())
        if len(names) <= 1:
            QMessageBox.information(self, "EQ preset", "At least one EQ preset must remain.")
            return

        answer = QMessageBox.question(
            self,
            "Delete EQ preset",
            f"Delete preset '{current}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        replacement = self.backend_controller.delete_eq_profile(self._current_channel_key(), current)
        if replacement:
            self._reload_profiles(preferred=replacement)
            self.status_label.setText(f"Deleted preset: {current}")
        else:
            self.status_label.setText("Could not delete EQ preset.")

    def _preview_band_label(self, index: int, raw: int) -> None:
        if not (0 <= index < len(self.band_controls)):
            return
        gain_label, _slider, _freq_label = self.band_controls[index]
        gain_label.setText(self._format_gain(self._raw_to_gain(raw)))

    def _eq_band_changed(self, index: int, raw: int) -> None:
        if self._syncing:
            return
        self._preview_band_label(index, raw)
        self._pending_band_index = index
        self.apply_timer.start()

    def _apply_pending_band(self) -> None:
        if self.backend_controller is None or self._pending_band_index is None:
            return

        index = int(self._pending_band_index)
        self._pending_band_index = None

        try:
            _gain_label, slider, _freq_label = self.band_controls[index]
        except Exception:
            return

        gain_db = self._raw_to_gain(slider.value())
        ok = self.backend_controller.set_eq_band_gain(
            self._current_channel_key(),
            index,
            gain_db,
            self._current_profile_name(),
        )
        if ok:
            self.status_label.setText(f"Saved band {index + 1}: {self._format_gain(gain_db)} dB")
        else:
            self.status_label.setText("Could not save EQ band.")





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
    PAD_BG_DARKNESS = 62

    def __init__(
        self,
        name: str,
        icon: str,
        meta: str,
        emoji_callback=None,
        delete_callback=None,
        play_callback=None,
        slot_key: str = "",
        background_path: str = "",
        background_callback=None,
        sound_callback=None,
        trim_callback=None,
        trim_db: float = 0.0,
    ):
        super().__init__()
        self._edit_enabled = False
        self._bulk_select_enabled = False
        self._bulk_selected = False
        self._emoji_callback = emoji_callback
        self._delete_callback = delete_callback
        self._play_callback = play_callback
        self._background_callback = background_callback
        self._sound_callback = sound_callback
        self._trim_callback = trim_callback
        self._slot_key = str(slot_key or "").strip()
        self._always_show_meta = False
        self._background_path = str(background_path or "").strip()
        self._background_pixmap = QPixmap()

        self.setObjectName("soundPadCard")
        self.setProperty("edit", "false")
        self.setProperty("bulkSelected", "false")
        self.setProperty("missingSound", "false")
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

        self.meta_label = HoverScrollLabel(meta)
        self.meta_label.setObjectName("soundPadMeta")
        self.meta_label.setAlignment(Qt.AlignCenter)
        self.meta_label.setFixedHeight(13)
        root.addWidget(self.meta_label)
        self.meta_label.setVisible(False)

        self.actions = QFrame()
        self.actions.setObjectName("soundPadActions")
        actions_outer = QVBoxLayout(self.actions)
        actions_outer.setContentsMargins(3, 2, 3, 3)
        actions_outer.setSpacing(3)

        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(3)
        actions_layout.addStretch(1)

        bg_button = QPushButton("🖼")
        bg_button.setObjectName("padIconButton")
        bg_button.setToolTip("Edit background")
        bg_button.clicked.connect(self._request_background)
        actions_layout.addWidget(bg_button)

        sound_button = QPushButton("🎵")
        sound_button.setObjectName("padIconButton")
        sound_button.setToolTip("Edit sound")
        sound_button.clicked.connect(self._request_sound)
        actions_layout.addWidget(sound_button)

        delete_button = CenterGlyphButton("🗑")
        delete_button.setObjectName("padDeleteButton")
        delete_button.setToolTip("Delete")
        delete_button.clicked.connect(self._request_delete)
        actions_layout.addWidget(delete_button)

        actions_layout.addStretch(1)
        actions_outer.addLayout(actions_layout)

        trim_layout = QHBoxLayout()
        trim_layout.setContentsMargins(0, 0, 0, 0)
        trim_layout.setSpacing(4)

        trim_down = QPushButton("−")
        trim_down.setObjectName("padIconButton")
        trim_down.setToolTip("Gain trim down 1 dB")
        trim_down.setMinimumHeight(24)
        trim_down.setMaximumHeight(24)
        trim_down.clicked.connect(lambda: self._change_trim_db(-1.0))
        trim_layout.addWidget(trim_down)

        self.trim_label = QLabel()
        self.trim_label.setObjectName("soundPadTrim")
        self.trim_label.setAlignment(Qt.AlignCenter)
        self.trim_label.setMinimumHeight(24)
        self.trim_label.setMaximumHeight(24)
        self.trim_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        trim_layout.addWidget(self.trim_label, 1)

        trim_up = QPushButton("+")
        trim_up.setObjectName("padIconButton")
        trim_up.setToolTip("Gain trim up 1 dB")
        trim_up.setMinimumHeight(24)
        trim_up.setMaximumHeight(24)
        trim_up.clicked.connect(lambda: self._change_trim_db(1.0))
        trim_layout.addWidget(trim_up)

        actions_outer.addLayout(trim_layout)

        self.actions.setVisible(False)
        root.addWidget(self.actions)
        self.set_trim_db(trim_db, emit=False)

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

    def slot_key(self) -> str:
        return self._slot_key

    def set_slot_key(self, slot_key: str) -> None:
        self._slot_key = str(slot_key or "").strip()

    def set_missing_sound(self, missing: bool, path_text: str = "") -> None:
        missing = bool(missing)
        self.setProperty("missingSound", "true" if missing else "false")
        if missing:
            self.icon_button.setText("⚠")
            self.meta_label.setText("File missing")
            self.meta_label.setVisible(True)
            self.meta_label.setToolTip(str(path_text or "Missing sound file"))
            self.setToolTip(str(path_text or "Missing sound file"))
        else:
            self.setToolTip("")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_display_name(self, name: str) -> None:
        clean = str(name or "").strip() or "Unnamed"
        self.name_label.setText(clean)
        self.name_editor.setText(clean)

    def set_meta(self, meta: str) -> None:
        self.meta_label.setText(str(meta or ""))

    def set_always_show_meta(self, enabled: bool) -> None:
        self._always_show_meta = bool(enabled)
        if hasattr(self, "meta_label"):
            self.meta_label.setVisible(bool(self._edit_enabled or self._always_show_meta))

    def set_pad_background_darkness(self, value: int) -> None:
        try:
            numeric = int(value)
        except Exception:
            numeric = self.PAD_BG_DARKNESS
        self._pad_bg_darkness = max(0, min(100, numeric))
        if getattr(self, "_background_path", ""):
            self._apply_background_style()

    def set_background_path(self, path: str) -> None:
        self._background_path = str(path or "").strip()
        if not hasattr(self, "_pad_bg_darkness"):
            self._pad_bg_darkness = self.PAD_BG_DARKNESS
        self._apply_background_style()

    def _darkened_background_path(self, bg_path: Path) -> str:
        darkness = max(0, min(100, int(getattr(self, "_pad_bg_darkness", self.PAD_BG_DARKNESS))))
        if darkness <= 0:
            return str(bg_path)

        try:
            stat = bg_path.stat()
            key = hashlib.sha256(f"{bg_path}|{stat.st_mtime_ns}|{darkness}".encode("utf-8", "ignore")).hexdigest()[:24]
            cache_dir = CONFIG_DIR / "pad-bg-cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached = cache_dir / f"{key}.png"
            if cached.is_file():
                return str(cached)

            source = QPixmap(str(bg_path))
            if source.isNull():
                return str(bg_path)

            size = QSize(640, 640)
            scaled = source.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            result = QPixmap(size)
            result.fill(Qt.transparent)

            painter = QPainter(result)
            x = (size.width() - scaled.width()) // 2
            y = (size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            alpha = int(max(0, min(215, darkness * 2.1)))
            painter.setOpacity(alpha / 255.0)
            painter.fillRect(result.rect(), Qt.GlobalColor.black)
            painter.end()

            if result.save(str(cached), "PNG"):
                return str(cached)
        except Exception:
            return str(bg_path)

        return str(bg_path)

    def _apply_background_style(self) -> None:
        bg_path = Path(getattr(self, "_background_path", "") or "").expanduser()
        if not bg_path.is_file():
            self._background_pixmap = QPixmap()
            self.setStyleSheet("")
            self.update()
            return

        pixmap = QPixmap(self._darkened_background_path(bg_path))
        self._background_pixmap = pixmap if not pixmap.isNull() else QPixmap()
        self.setStyleSheet("""
QFrame#soundPadCard {
    border-radius: 16px;
}
QFrame#soundPadCard QLabel#soundPadName,
QFrame#soundPadCard QLabel#soundPadMeta,
QFrame#soundPadCard QLabel#soundPadTrim {
    background: rgba(0, 0, 0, 178);
    border-radius: 8px;
    padding: 2px 6px;
}
QFrame#soundPadCard QPushButton#soundPadEmoji {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    background: rgba(0, 0, 0, 230);
    border-radius: 17px;
}
""")
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        pixmap = getattr(self, "_background_pixmap", QPixmap())
        if pixmap.isNull():
            return

        rect = self.rect()
        if rect.width() <= 1 or rect.height() <= 1:
            return

        scaled = pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (rect.width() - scaled.width()) // 2
        y = (rect.height() - scaled.height()) // 2

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 16, 16)
        painter.setClipPath(path)
        painter.drawPixmap(x, y, scaled)
        painter.end()

    def _request_background(self) -> None:
        if self._edit_enabled and self._background_callback is not None:
            self._background_callback(self)

    def _request_sound(self) -> None:
        if self._edit_enabled and self._sound_callback is not None:
            self._sound_callback(self)

    def trim_db(self) -> float:
        return float(getattr(self, "_trim_db", 0.0))

    def set_trim_db(self, value: float, emit: bool = False) -> None:
        try:
            numeric = float(value)
        except Exception:
            numeric = 0.0
        self._trim_db = max(-24.0, min(24.0, numeric))
        if hasattr(self, "trim_label"):
            if abs(self._trim_db) < 0.05:
                text = "0 dB"
            else:
                text = f"{self._trim_db:+.0f} dB"
            self.trim_label.setText(text)
            self.trim_label.setToolTip(f"Manual gain trim: {text}")
        if emit and self._trim_callback is not None:
            self._trim_callback(self, self._trim_db)

    def _change_trim_db(self, delta: float) -> None:
        self.set_trim_db(self.trim_db() + float(delta), emit=True)

    def set_bulk_select_enabled(self, enabled: bool) -> None:
        self._bulk_select_enabled = bool(enabled)

        if enabled:
            self.actions.setVisible(False)
            self.setProperty("edit", "false")
            self.setMinimumHeight(70)
            if hasattr(self, "meta_label"):
                self.meta_label.setVisible(False)
        else:
            self.set_bulk_selected(False)
            self.actions.setVisible(self._edit_enabled)
            self.setProperty("edit", "true" if self._edit_enabled else "false")
            self.setMinimumHeight(100 if self._edit_enabled else 70)
            if hasattr(self, "meta_label"):
                self.meta_label.setVisible(bool(self._edit_enabled or getattr(self, "_always_show_meta", False)))

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
        enabled = bool(enabled)
        if self._edit_enabled == enabled and self.actions.isVisible() == enabled:
            return

        self._edit_enabled = enabled
        self.setProperty("edit", "true" if enabled else "false")
        self.actions.setVisible(enabled)
        self.setMinimumHeight(100 if enabled else 70)

        if hasattr(self, "meta_label"):
            self.meta_label.setVisible(bool(enabled or getattr(self, "_always_show_meta", False)))

        if not enabled:
            self.name_editor.setVisible(False)
            self.name_label.setVisible(True)
            if self._bulk_select_enabled:
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

    def _read_pad_bg_darkness_setting(self) -> int:
        settings_path = CONFIG_DIR / "settings.json"
        try:
            if settings_path.is_file():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return max(0, min(100, int(data.get("glass_pad_bg_darkness", 62))))
        except Exception:
            pass
        return 62

    def _save_pad_bg_darkness_setting(self, value: int) -> None:
        settings_path = CONFIG_DIR / "settings.json"
        try:
            data = {}
            if settings_path.is_file():
                loaded = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            data["glass_pad_bg_darkness"] = int(max(0, min(100, value)))
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _set_pad_bg_darkness(self, value: int, persist: bool = True) -> None:
        try:
            numeric = int(value)
        except Exception:
            numeric = 62
        self._pad_bg_darkness = max(0, min(100, numeric))
        if persist:
            self._save_pad_bg_darkness_setting(self._pad_bg_darkness)

        host = getattr(self, "grid_host", None)
        scroll = getattr(self, "grid_scroll", None)
        if host is not None:
            host.setUpdatesEnabled(False)
        if scroll is not None:
            scroll.setUpdatesEnabled(False)
        try:
            for card in getattr(self, "pad_cards", []):
                setter = getattr(card, "set_pad_background_darkness", None)
                if callable(setter):
                    setter(self._pad_bg_darkness)
        finally:
            if host is not None:
                host.setUpdatesEnabled(True)
            if scroll is not None:
                scroll.setUpdatesEnabled(True)

    def _queue_pad_bg_darkness(self, value: int) -> None:
        self._pending_pad_bg_darkness = int(value)
        self._pad_bg_darkness_timer.start()

    def _apply_queued_pad_bg_darkness(self) -> None:
        self._set_pad_bg_darkness(int(getattr(self, "_pending_pad_bg_darkness", self._pad_bg_darkness)))

    def _apply_responsive_card_heights(self) -> None:
        if bool(getattr(self, "_show_detach", True)):
            return
        if not hasattr(self, "grid_scroll") or not hasattr(self, "grid"):
            return

        columns = max(1, int(getattr(self, "_columns", 1)))
        viewport_width = max(1, self.grid_scroll.viewport().width())
        spacing = max(0, int(self.grid.horizontalSpacing()))
        card_width = max(72, (viewport_width - spacing * max(0, columns - 1)) // columns)
        target_height = max(116, min(176, int(card_width * 0.92)))

        for card in getattr(self, "pad_cards", []):
            if card.minimumHeight() != target_height:
                card.setMinimumHeight(target_height)

    def _update_responsive_columns(self) -> None:
        if not hasattr(self, "grid_scroll"):
            return

        if bool(getattr(self, "_show_detach", True)):
            return

        width = max(1, self.grid_scroll.viewport().width())
        spacing = 4 if width < 900 else 5
        if self.grid.horizontalSpacing() != spacing:
            self.grid.setHorizontalSpacing(spacing)
            self.grid.setVerticalSpacing(spacing)

        min_card_width = 118 if width >= 900 else 132
        columns = max(1, min(12, (width + spacing) // max(1, min_card_width + spacing)))

        try:
            self.grid_host.setMinimumWidth(width)
        except Exception:
            pass

        if columns != self._columns:
            self._columns = columns
            self._reflow_grid()
        else:
            self._apply_responsive_card_heights()

    def _read_soundboard_volume_setting(self) -> int:
        try:
            if SOUNDBOARD_PATH.is_file():
                data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return max(0, min(100, int(data.get("global_volume", 100))))
        except Exception:
            pass
        return 100

    def _read_soundboard_auto_level_enabled(self) -> bool:
        try:
            if SOUNDBOARD_PATH.is_file():
                data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return bool(data.get("auto_level_enabled", False))
        except Exception:
            pass
        return False

    def _save_soundboard_auto_level_enabled(self, enabled: bool) -> None:
        try:
            if SOUNDBOARD_PATH.is_file():
                loaded = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            else:
                loaded = {"slots": []}

            if isinstance(loaded, list):
                data = {"slots": loaded}
            elif isinstance(loaded, dict):
                data = loaded
            else:
                data = {"slots": []}

            if not isinstance(data.get("slots"), list):
                data["slots"] = []

            data["auto_level_enabled"] = bool(enabled)
            SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _save_soundboard_volume_setting(self, value: int) -> None:
        numeric = int(max(0, min(100, value)))
        try:
            if SOUNDBOARD_PATH.is_file():
                loaded = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
            else:
                loaded = {"slots": []}

            if isinstance(loaded, list):
                data = {"slots": loaded}
            elif isinstance(loaded, dict):
                data = loaded
            else:
                data = {"slots": []}

            if not isinstance(data.get("slots"), list):
                data["slots"] = []

            data["global_volume"] = numeric
            SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
            SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _set_soundboard_volume(self, value: int, persist: bool = True) -> None:
        try:
            numeric = int(value)
        except Exception:
            numeric = 100
        self._soundboard_volume = max(0, min(100, numeric))

        if persist:
            self._save_soundboard_volume_setting(self._soundboard_volume)

    def _set_soundboard_auto_level_enabled(self, enabled: bool, persist: bool = True) -> None:
        self._soundboard_auto_level_enabled = bool(enabled)

        check = getattr(self, "soundboard_auto_level_check", None)
        if check is not None:
            check.setText("Auto-level")
            check.setToolTip(
                "Auto-level is enabled. Manual dB trim still applies."
                if self._soundboard_auto_level_enabled
                else "Auto-level is disabled. Only manual dB trim applies."
            )
            if check.isChecked() != self._soundboard_auto_level_enabled:
                old = check.blockSignals(True)
                try:
                    check.setChecked(self._soundboard_auto_level_enabled)
                finally:
                    check.blockSignals(old)

        if persist:
            self._save_soundboard_auto_level_enabled(self._soundboard_auto_level_enabled)

    def _analyze_soundboard_auto_level(self) -> None:
        if bool(getattr(self, "_soundboard_auto_level_analyzing", False)):
            return

        self._soundboard_auto_level_analyzing = True
        result_queue = queue.Queue(maxsize=1)
        self._soundboard_auto_level_result_queue = result_queue

        button = getattr(self, "soundboard_analyze_button", None)
        if button is not None:
            button.setEnabled(False)
            button.setText("…")

        worker = threading.Thread(
            target=self._analyze_soundboard_auto_level_worker,
            args=(result_queue,),
            name="KSoundsAutoLevelAnalyze",
            daemon=True,
        )
        self._soundboard_auto_level_worker = worker
        worker.start()
        QTimer.singleShot(150, self._poll_soundboard_auto_level_analysis)

    def _analyze_soundboard_auto_level_worker(self, result_queue) -> None:
        try:
            result = self._analyze_soundboard_auto_level_now()
        except Exception as exc:
            result = {"ok": False, "message": f"Analyze failed: {exc}"}

        try:
            result_queue.put_nowait(result)
        except Exception:
            pass

    def _poll_soundboard_auto_level_analysis(self) -> None:
        result_queue = getattr(self, "_soundboard_auto_level_result_queue", None)
        if result_queue is None:
            return

        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            if bool(getattr(self, "_soundboard_auto_level_analyzing", False)):
                QTimer.singleShot(150, self._poll_soundboard_auto_level_analysis)
            return

        self._soundboard_auto_level_analyzing = False

        button = getattr(self, "soundboard_analyze_button", None)
        if button is not None:
            button.setEnabled(True)
            button.setText("↻")

        message = str(result.get("message") or "Analyze finished.")
        if bool(result.get("ok")):
            QMessageBox.information(self, "Analyze Auto-level", message)
        else:
            QMessageBox.warning(self, "Analyze Auto-level", message)

    def _analyze_soundboard_auto_level_now(self) -> dict:
        if not SOUNDBOARD_PATH.is_file():
            return {"ok": False, "message": "soundboard.json not found."}

        raw_bytes = SOUNDBOARD_PATH.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
        slots = data.get("slots", [])
        if not isinstance(slots, list):
            return {"ok": False, "message": "soundboard.json has no valid slots list."}

        backup_path = SOUNDBOARD_PATH.with_name(
            f"soundboard.json.backup-before-analyze-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        backup_path.write_bytes(raw_bytes)

        target_peak_db = -3.0
        min_gain = 0.05
        max_gain = 1.5

        changed = 0
        present = 0
        missing = 0
        failed = 0
        values: list[float] = []

        for slot in slots:
            if not isinstance(slot, dict):
                continue

            path_text = str(slot.get("path") or "").strip()
            if not path_text:
                continue

            sound_path = Path(path_text).expanduser()
            if not sound_path.is_file():
                missing += 1
                continue

            present += 1

            try:
                proc = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostats",
                        "-i",
                        str(sound_path),
                        "-filter:a",
                        "volumedetect",
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except FileNotFoundError:
                return {
                    "ok": False,
                    "message": "ffmpeg was not found. Auto-level analysis could not run.",
                }
            except Exception:
                failed += 1
                continue

            output = f"{proc.stdout}\n{proc.stderr}"
            match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
            if not match:
                failed += 1
                continue

            try:
                max_db = float(match.group(1))
            except Exception:
                failed += 1
                continue

            gain = 10 ** ((target_peak_db - max_db) / 20.0)
            gain = round(max(min_gain, min(max_gain, gain)), 4)

            if slot.get("auto_gain") != gain or str(slot.get("analyzed_path") or "") != str(sound_path):
                slot["auto_gain"] = gain
                slot["analyzed_path"] = str(sound_path)
                changed += 1

            values.append(gain)

        SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        if values:
            values_sorted = sorted(values)
            median = values_sorted[len(values_sorted) // 2]
            message = (
                f"Analyzed {present} sound(s).\n"
                f"Changed: {changed} · Missing: {missing} · Failed: {failed}\n"
                f"Gain min/median/max: {min(values):.4g} / {median:.4g} / {max(values):.4g}\n"
                f"> 1.0: {sum(1 for value in values if value > 1.0)} · capped at 1.5: {sum(1 for value in values if abs(value - 1.5) < 0.0001)}\n"
                f"Backup: {backup_path}"
            )
        else:
            message = (
                f"No present sound files were analyzed.\n"
                f"Missing: {missing} · Failed: {failed}\n"
                f"Backup: {backup_path}"
            )

        return {"ok": failed == 0, "message": message}

    def _queue_soundboard_volume(self, value: int) -> None:
        self._pending_soundboard_volume = int(value)
        self._soundboard_volume_timer.start()

    def _apply_queued_soundboard_volume(self) -> None:
        self._set_soundboard_volume(int(getattr(self, "_pending_soundboard_volume", self._soundboard_volume)))

    def __init__(self, detach_callback=None, columns: int = 2, show_detach: bool = True):
        super().__init__()
        self._detach_callback = detach_callback
        self._columns = max(1, columns)
        self._show_detach = show_detach
        self._edit_mode = False
        self._bulk_delete_mode = False
        self._active_emoji_card: SoundPadCard | None = None
        self._soundboard_bus_player_processes: list[subprocess.Popen] = []
        self.pad_cards: list[SoundPadCard] = []
        self._soundboard_volume = self._read_soundboard_volume_setting()
        self._soundboard_auto_level_enabled = self._read_soundboard_auto_level_enabled()
        self._pending_soundboard_volume = self._soundboard_volume
        self._soundboard_volume_timer = QTimer(self)
        self._soundboard_volume_timer.setSingleShot(True)
        self._soundboard_volume_timer.setInterval(120)
        self._soundboard_volume_timer.timeout.connect(self._apply_queued_soundboard_volume)
        self._pad_bg_darkness = self._read_pad_bg_darkness_setting()
        self._pending_pad_bg_darkness = self._pad_bg_darkness
        self._pad_bg_darkness_timer = QTimer(self)
        self._pad_bg_darkness_timer.setSingleShot(True)
        self._pad_bg_darkness_timer.setInterval(120)
        self._pad_bg_darkness_timer.timeout.connect(self._apply_queued_pad_bg_darkness)

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

        connect = QPushButton("Pair Android")
        connect.setObjectName("padTopButton")
        connect.setToolTip("Show Android pairing code")
        connect.clicked.connect(self._pair_android_remote)
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

        pad_dark_row = QFrame()
        pad_dark_row.setObjectName("padBgDarknessControls")
        pad_dark_layout = QHBoxLayout(pad_dark_row)
        pad_dark_layout.setContentsMargins(9, 5, 9, 5)
        pad_dark_layout.setSpacing(8)

        pad_dark_label = QLabel("Pad BG darkness")
        pad_dark_label.setObjectName("detachedBgLabel")
        pad_dark_layout.addWidget(pad_dark_label)

        self.pad_bg_darkness_slider = NoWheelSlider(Qt.Horizontal)
        self.pad_bg_darkness_slider.setObjectName("padBgDarknessSlider")
        self.pad_bg_darkness_slider.setRange(0, 100)
        self.pad_bg_darkness_slider.setValue(int(self._pad_bg_darkness))
        self.pad_bg_darkness_slider.setMinimumHeight(24)
        self.pad_bg_darkness_slider.valueChanged.connect(lambda value: self._queue_pad_bg_darkness(int(value)))
        pad_dark_layout.addWidget(self.pad_bg_darkness_slider, 1)

        root.addWidget(pad_dark_row)

        self.grid_scroll = AdaptiveScrollArea()
        self.grid_scroll.setObjectName("padsGridScroll")
        self.grid_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        pads_scrollbar = self.grid_scroll.verticalScrollBar()
        pads_scrollbar.setObjectName("padsGridScrollbar")
        pads_scrollbar.setFixedWidth(8)

        self.grid_host = QWidget()
        self.grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(5)
        self.grid.setVerticalSpacing(5)

        self.grid_scroll.setWidget(self.grid_host)
        self.grid_scroll._schedule_margin_update()
        root.addWidget(self.grid_scroll, 1)

        volume_row = QFrame()
        volume_row.setObjectName("soundboardVolumeControls")
        volume_layout = QHBoxLayout(volume_row)
        volume_layout.setContentsMargins(7, 4, 7, 4)
        volume_layout.setSpacing(8)

        soundboard_volume_minus = QLabel("-")
        soundboard_volume_minus.setObjectName("soundboardVolumeSign")
        soundboard_volume_minus.setAlignment(Qt.AlignCenter)
        volume_layout.addWidget(soundboard_volume_minus)

        self.soundboard_volume_slider = NoWheelSlider(Qt.Horizontal)
        self.soundboard_volume_slider.setObjectName("soundboardVolumeSlider")
        self.soundboard_volume_slider.setRange(0, 100)
        self.soundboard_volume_slider.setValue(int(self._soundboard_volume))
        self.soundboard_volume_slider.setMinimumHeight(24)
        self.soundboard_volume_slider.valueChanged.connect(lambda value: self._queue_soundboard_volume(int(value)))
        volume_layout.addWidget(self.soundboard_volume_slider, 1)

        soundboard_volume_plus = QLabel("+")
        soundboard_volume_plus.setObjectName("soundboardVolumeSign")
        soundboard_volume_plus.setAlignment(Qt.AlignCenter)
        volume_layout.addWidget(soundboard_volume_plus)

        self.soundboard_auto_level_check = QCheckBox("Auto-level")
        self.soundboard_auto_level_check.setObjectName("soundboardAutoLevelToggle")
        self.soundboard_auto_level_check.setMinimumWidth(96)
        self.soundboard_auto_level_check.setMinimumHeight(24)
        self.soundboard_auto_level_check.setMaximumHeight(24)
        self.soundboard_auto_level_check.setCursor(Qt.PointingHandCursor)
        self.soundboard_auto_level_check.setChecked(bool(self._soundboard_auto_level_enabled))
        self.soundboard_auto_level_check.setText("Auto-level")
        self.soundboard_auto_level_check.setToolTip(
            "Auto-level is enabled. Manual dB trim still applies."
            if self._soundboard_auto_level_enabled
            else "Auto-level is disabled. Only manual dB trim applies."
        )
        self.soundboard_auto_level_check.toggled.connect(
            lambda checked: self._set_soundboard_auto_level_enabled(bool(checked))
        )
        volume_layout.addWidget(self.soundboard_auto_level_check)

        root.addWidget(volume_row)

        for name, icon, meta, slot_key, background_path, trim_db, sound_path in self._load_real_soundboard_pads():
            self._add_pad(name, icon, meta, slot_key=slot_key, background_path=background_path, trim_db=trim_db, sound_path=sound_path)

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

        self.pair_overlay = None
        self.pair_code_input = None

        self._set_pad_bg_darkness(self._pad_bg_darkness, persist=False)
        QTimer.singleShot(0, self._update_responsive_columns)

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
        self._update_responsive_columns()
        self._position_emoji_overlay()
        self._position_pair_overlay()

    def _pair_overlay_parent(self):
        try:
            parent = self.window()
            if parent is not None:
                return parent
        except Exception:
            pass
        return self

    def _ensure_pair_overlay(self) -> QFrame:
        parent = self._pair_overlay_parent()
        overlay = getattr(self, "pair_overlay", None)
        if overlay is not None and overlay.parent() is parent:
            return overlay

        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except Exception:
                pass

        overlay = QFrame(parent)
        overlay.setObjectName("pairOverlayDim")
        overlay.setAttribute(Qt.WA_StyledBackground, True)

        root = QVBoxLayout(overlay)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)
        root.addStretch(1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)

        card = QFrame(overlay)
        card.setObjectName("pairOverlayCard")
        card.setMaximumWidth(420)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Android pairing code")
        title.setObjectName("pairOverlayTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        code = QLineEdit("")
        code.setObjectName("pairOverlayCode")
        code.setReadOnly(True)
        code.setAlignment(Qt.AlignCenter)
        code.setMinimumHeight(46)
        layout.addWidget(code)
        self.pair_code_input = code

        hint = QLabel(
            "Open K-Sounds Remote on Android, search the PC, then enter this code.\n"
            "The code expires in 5 minutes."
        )
        hint.setObjectName("pairOverlayHint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        copy_button = QPushButton("Copy")
        copy_button.setObjectName("pairOverlayButton")
        copy_button.clicked.connect(self._copy_pair_code)
        buttons.addWidget(copy_button)

        close_button = QPushButton("Close")
        close_button.setObjectName("pairOverlayButton")
        close_button.clicked.connect(self._hide_pair_overlay)
        buttons.addWidget(close_button)

        layout.addLayout(buttons)

        row.addWidget(card)
        row.addStretch(1)

        root.addLayout(row)
        root.addStretch(1)

        overlay.setStyleSheet("""
QFrame#pairOverlayDim {
    background: rgba(0, 0, 0, 150);
}
QFrame#pairOverlayCard {
    background: rgba(7, 10, 18, 245);
    border: 1px solid rgba(62, 216, 255, 95);
    border-radius: 18px;
}
QLabel#pairOverlayTitle {
    color: rgba(236, 247, 255, 245);
    font-size: 16px;
    font-weight: 800;
}
QLineEdit#pairOverlayCode {
    color: white;
    background: rgba(0, 0, 0, 190);
    border: 1px solid rgba(62, 216, 255, 120);
    border-radius: 12px;
    font-size: 26px;
    font-weight: 900;
    letter-spacing: 5px;
}
QLabel#pairOverlayHint {
    color: rgba(198, 218, 232, 220);
    font-size: 12px;
}
QPushButton#pairOverlayButton {
    color: white;
    background: rgba(22, 42, 70, 220);
    border: 1px solid rgba(62, 216, 255, 90);
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 700;
}
QPushButton#pairOverlayButton:hover {
    background: rgba(38, 78, 118, 235);
}
""")

        self.pair_overlay = overlay
        self._position_pair_overlay()
        return overlay

    def _position_pair_overlay(self) -> None:
        overlay = getattr(self, "pair_overlay", None)
        if overlay is None:
            return

        parent = overlay.parentWidget()
        if parent is None:
            return

        try:
            overlay.setGeometry(parent.rect())
        except Exception:
            overlay.setGeometry(self.rect())

    def _show_pair_overlay(self, pin: str) -> None:
        overlay = self._ensure_pair_overlay()
        self._position_pair_overlay()

        code = getattr(self, "pair_code_input", None)
        if code is not None:
            code.setText(str(pin or ""))
            code.selectAll()
            code.setFocus()

        overlay.show()
        overlay.raise_()

    def _hide_pair_overlay(self) -> None:
        overlay = getattr(self, "pair_overlay", None)
        if overlay is not None:
            overlay.hide()

    def _copy_pair_code(self) -> None:
        code = getattr(self, "pair_code_input", None)
        if code is None:
            return
        try:
            QApplication.clipboard().setText(code.text())
        except Exception:
            pass

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
            self._persist_card_emoji(self._active_emoji_card, emoji)
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

    def _load_real_soundboard_pads(self) -> list[tuple[str, str, str, str, str, float, str]]:
        pads: list[tuple[str, str, str, str, str, float, str]] = []

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
            background_path = str(slot.get("background_path") or "").strip()
            try:
                trim_db = max(-24.0, min(24.0, float(slot.get("trim_db", 0.0) or 0.0)))
            except Exception:
                trim_db = 0.0

            if path_text:
                sound_path = Path(path_text).expanduser()
                filename = sound_path.name or "sound"
                status = route if sound_path.exists() else "missing"
                meta = f"{status} · {filename}"
            else:
                meta = route

            pads.append((label, icon, meta, slot_key, background_path, trim_db, path_text))

        if pads:
            return pads

        if SOUNDBOARD_PATH.is_file():
            return [("No saved sounds", "🎧", "soundboard.json empty", "", "", 0.0, "")]

        return [("No soundboard file", "🎧", "soundboard.json missing", "", "", 0.0, "")]


    def _cleanup_soundboard_bus_players(self) -> None:
        active: list[subprocess.Popen] = []
        for proc in list(getattr(self, "_soundboard_bus_player_processes", [])):
            try:
                if proc.poll() is None:
                    active.append(proc)
            except Exception:
                pass
        self._soundboard_bus_player_processes = active

    def _terminate_soundboard_bus_proc(self, proc: subprocess.Popen) -> bool:
        try:
            if proc.poll() is not None:
                return False
        except Exception:
            return False

        stopped = False
        try:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

            try:
                proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=0.25)
                except Exception:
                    pass
            stopped = True
        except Exception:
            pass
        return stopped

    def _soundboard_player_sink_input_ids(self) -> list[str]:
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            timeout=1.2,
        )
        if result.returncode != 0:
            return []

        ids: list[str] = []
        current_id = ""
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_id, current_lines
            if not current_id:
                current_lines = []
                return
            block = "\n".join(current_lines)
            if 'media.name = "K-Sounds-Hub-Soundboard-Player"' in block:
                ids.append(current_id)
            current_id = ""
            current_lines = []

        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            match = re.match(r"Sink Input #(\d+)", line)
            if match:
                flush()
                current_id = match.group(1)
                current_lines = [line]
                continue
            if current_id:
                current_lines.append(line)

        flush()
        return ids

    def _kill_soundboard_bus_players(self) -> int:
        # The Glass pads player uses a fire-and-forget bash ffmpeg|pacat pipeline.
        # Track and stop its process group directly; pactl media-name cleanup is
        # kept as a fallback for older/external players.
        stopped = 0

        for proc in list(getattr(self, "_soundboard_bus_player_processes", [])):
            if self._terminate_soundboard_bus_proc(proc):
                stopped += 1
        self._soundboard_bus_player_processes = []

        for stream_id in self._soundboard_player_sink_input_ids():
            try:
                result = subprocess.run(
                    ["pactl", "kill-sink-input", str(stream_id)],
                    capture_output=True,
                    text=True,
                    timeout=0.8,
                )
                if result.returncode == 0:
                    stopped += 1
            except Exception:
                pass
        return stopped

    def _stop_all_sounds(self) -> None:
        button = getattr(self, "stop_all_button", None)
        if button is not None:
            button.setEnabled(False)
            QTimer.singleShot(180, lambda b=button: b.setEnabled(True))

        self._kill_soundboard_bus_players()

    def _remote_server_reachable(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 8765), timeout=0.25):
                return True
        except Exception:
            return False

    def _start_android_remote_server_if_needed(self) -> bool:
        if self._remote_server_reachable():
            return True

        repo_root = Path(__file__).resolve().parents[2]
        remote_script = repo_root / "tools" / "soundboard_remote" / "ksound_soundboard_web.py"
        if not remote_script.is_file():
            QMessageBox.warning(self, "Pair Android", f"Remote server script not found.\n\n{remote_script}")
            return False

        log_path = CONFIG_DIR / "soundboard-web.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("ab")
            subprocess.Popen(
                [sys.executable, str(remote_script)],
                cwd=str(repo_root),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Pair Android", f"Could not start Android remote server.\n\n{exc}")
            return False

        return True

    def _pair_android_remote(self) -> None:
        if not self._start_android_remote_server_if_needed():
            return

        pin = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = time.time() + 300

        pairing_path = CONFIG_DIR / "soundboard_pairing.json"
        try:
            pairing_path.parent.mkdir(parents=True, exist_ok=True)
            pairing_path.write_text(
                json.dumps(
                    {
                        "pin": pin,
                        "expires_at": expires_at,
                        "created_at": time.time(),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            try:
                pairing_path.chmod(0o600)
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.warning(self, "Pair Android", f"Could not write pairing code.\n\n{exc}")
            return

        self._show_pair_overlay(pin)


    def _slot_for_key(self, slot_key: str) -> dict | None:
        key = str(slot_key or "").strip()
        if not key:
            return None

        data = self._read_soundboard_document()
        slots = data.get("slots", [])
        if not isinstance(slots, list):
            return None

        for index, slot in enumerate(slots):
            if not isinstance(slot, dict):
                continue
            candidates = {
                str(slot.get("id") or "").strip(),
                str(slot.get("label") or "").strip(),
                str(index + 1),
            }
            if key in candidates:
                return slot
        return None

    def _play_slot_to_soundboard_bus(self, slot: dict) -> bool:
        path = Path(str(slot.get("path") or "")).expanduser()
        if not path.is_file():
            return False

        try:
            root = self._read_soundboard_document()
            global_volume = max(0, min(150, int(root.get("global_volume", 100) or 100)))
            auto_level_enabled = bool(root.get("auto_level_enabled", False))
        except Exception:
            global_volume = 100
            auto_level_enabled = False

        try:
            slot_volume = max(0, min(150, int(slot.get("volume", 100) or 100)))
        except Exception:
            slot_volume = 100

        if auto_level_enabled:
            try:
                auto_gain = max(0.05, min(1.5, float(slot.get("auto_gain", 1.0) or 1.0)))
            except Exception:
                auto_gain = 1.0
        else:
            auto_gain = 1.0

        try:
            trim_db = max(-24.0, min(24.0, float(slot.get("trim_db", 0.0) or 0.0)))
        except Exception:
            trim_db = 0.0

        gain = (global_volume / 100.0) * (slot_volume / 100.0) * auto_gain * (10.0 ** (trim_db / 20.0))
        gain = max(0.0, min(3.0, gain))

        cmd = (
            "ffmpeg -v error -nostdin -i "
            + shlex.quote(str(path))
            + f" -filter:a volume={gain:.4f} "
            + " -f f32le -ac 2 -ar 48000 pipe:1 | "
            + "pacat --playback --device=soundboard --raw --format=float32le --rate=48000 --channels=2 "
            + "--latency-msec=42 --process-time-msec=12 "
            + "--property=media.name=K-Sounds-Hub-Soundboard-Player"
        )

        self._cleanup_soundboard_bus_players()
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._soundboard_bus_player_processes.append(proc)
        QTimer.singleShot(500, self._cleanup_soundboard_bus_players)
        QTimer.singleShot(2500, self._cleanup_soundboard_bus_players)
        return True

    def _play_pad(self, slot_key: str) -> None:
        if self._edit_mode or self._bulk_delete_mode:
            return

        try:
            controller = getattr(self.window(), "backend_controller", None)
            # Routes are applied on startup and whenever the Soundboard routing
            # controls change. Do not run heavy pactl route validation on every
            # pad click: it stalls Glass meters/UI exactly when a sound starts.
            slot = self._slot_for_key(slot_key)
            if not slot or not self._play_slot_to_soundboard_bus(slot):
                QMessageBox.warning(self, "Soundboard playback", "This sound could not be found or could not be played.")

            if controller is not None:
                QTimer.singleShot(120, controller._unmute_soundboard_output_streams)
        except Exception as exc:
            QMessageBox.warning(self, "Soundboard playback", f"Could not play this sound.\n\n{exc}")

    def _read_soundboard_document(self) -> dict:
        if not SOUNDBOARD_PATH.is_file():
            return {"slots": []}
        try:
            data = json.loads(SOUNDBOARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"slots": []}
        if isinstance(data, list):
            return {"slots": data}
        if isinstance(data, dict):
            if not isinstance(data.get("slots"), list):
                data["slots"] = []
            return data
        return {"slots": []}

    def _write_soundboard_document(self, data: dict) -> None:
        SOUNDBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOUNDBOARD_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _slot_index_for_card(self, slots: list, card: SoundPadCard) -> int | None:
        key = card.slot_key()
        if key:
            for index, slot in enumerate(slots):
                if isinstance(slot, dict) and str(slot.get("id") or "").strip() == key:
                    return index
            if key.isdigit():
                index = int(key) - 1
                if 0 <= index < len(slots):
                    return index
        return None

    def _ensure_slot_for_card(self, card: SoundPadCard) -> tuple[dict, list, int]:
        data = self._read_soundboard_document()
        slots = data.setdefault("slots", [])
        index = self._slot_index_for_card(slots, card)

        if index is None:
            slot = {
                "id": f"glass-{int(time.time() * 1000)}",
                "label": card.display_name() if not card.display_name().startswith("New pad") else "New sound",
                "path": "",
                "background_path": "",
                "volume": 80,
                "shortcut": "",
                "output_channel": "media",
                "send_to_micro": False,
                "auto_gain": 1.0,
                "analyzed_path": "",
                "trim_db": 0.0,
            }
            slots.append(slot)
            index = len(slots) - 1
            card.set_slot_key(str(slot["id"]))

        return data, slots, index

    def _refresh_soundboard_after_edit(self) -> None:
        # Glass pads read soundboard.json directly; there is no hidden playback dialog to sync.
        return

    def _persist_card_emoji(self, card: SoundPadCard, emoji: str) -> None:
        data, slots, index = self._ensure_slot_for_card(card)
        slot = slots[index]
        slot["emoji"] = str(emoji or "").strip()
        slot["icon"] = str(emoji or "").strip()
        self._write_soundboard_document(data)
        self._refresh_soundboard_after_edit()

    def _set_card_trim_db(self, card: SoundPadCard, trim_db: float) -> None:
        data, slots, index = self._ensure_slot_for_card(card)
        slot = slots[index]
        try:
            numeric = float(trim_db)
        except Exception:
            numeric = 0.0
        slot["trim_db"] = max(-24.0, min(24.0, numeric))
        self._write_soundboard_document(data)
        self._refresh_soundboard_after_edit()

    def _choose_pad_sound(self, card: SoundPadCard) -> None:
        data, slots, index = self._ensure_slot_for_card(card)
        slot = slots[index]
        current = str(slot.get("path") or "").strip()
        start_dir = str(Path(current).expanduser().parent) if current else str(Path.home())

        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Choose pad sound",
            start_dir,
            "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*)",
        )
        if not chosen:
            return

        sound_path = Path(chosen).expanduser()
        slot["path"] = str(sound_path)

        old_label = str(slot.get("label") or "").strip()
        if not old_label or old_label.upper() in {"SOUND", "EMPTY"} or old_label.startswith("New pad") or old_label == "New sound":
            slot["label"] = sound_path.stem
            card.set_display_name(sound_path.stem)

        route = self._format_soundboard_route(str(slot.get("output_channel") or "media"))
        card.set_meta(f"{route} · {sound_path.name}")
        self._write_soundboard_document(data)
        self._refresh_soundboard_after_edit()

    def _choose_pad_background(self, card: SoundPadCard) -> None:
        data, slots, index = self._ensure_slot_for_card(card)
        slot = slots[index]
        current = str(slot.get("background_path") or "").strip()
        start_dir = str(Path(current).expanduser().parent) if current else str(Path.home())

        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Choose pad background",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not chosen:
            return

        bg_path = str(Path(chosen).expanduser())
        slot["background_path"] = bg_path
        card.set_background_path(bg_path)
        self._write_soundboard_document(data)
        self._refresh_soundboard_after_edit()

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

        self.grid_host.setUpdatesEnabled(False)
        self.grid_scroll.setUpdatesEnabled(False)
        try:
            for card in self.pad_cards:
                card.set_edit_mode(enabled)
        finally:
            self.grid_host.setUpdatesEnabled(True)
            self.grid_scroll.setUpdatesEnabled(True)

        QTimer.singleShot(0, self._update_responsive_columns)

    def _add_pad(self, name: str | None = None, icon: str = "🎧", meta: str = "new", slot_key: str = "", background_path: str = "", trim_db: float = 0.0, sound_path: str = "") -> None:
        if name is None or isinstance(name, bool):
            name = f"New pad {len(self.pad_cards) + 1}"
            icon = "+"
            meta = "empty"
            slot_key = ""
            background_path = ""
            trim_db = 0.0
            sound_path = ""

        card = SoundPadCard(
            name,
            icon,
            meta,
            emoji_callback=self._show_emoji_palette,
            delete_callback=self._confirm_delete_card,
            play_callback=self._play_pad,
            slot_key=slot_key,
            background_path=background_path,
            background_callback=self._choose_pad_background,
            sound_callback=self._choose_pad_sound,
            trim_callback=self._set_card_trim_db,
            trim_db=trim_db,
        )
        if hasattr(card, "set_always_show_meta"):
            card.set_always_show_meta(not bool(self._show_detach))
        if hasattr(card, "set_pad_background_darkness"):
            card.set_pad_background_darkness(self._pad_bg_darkness)
        if background_path:
            card.set_background_path(background_path)
        if str(meta or "").startswith("missing ·") and hasattr(card, "set_missing_sound"):
            card.set_missing_sound(True, sound_path)
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

        max_columns_to_clear = max(len(self.pad_cards), self._columns + 8, 16)
        for col in range(max_columns_to_clear):
            self.grid.setColumnMinimumWidth(col, 0)
            self.grid.setColumnStretch(col, 0)

        for col in range(self._columns):
            self.grid.setColumnMinimumWidth(col, 0)
            self.grid.setColumnStretch(col, 1)

        self._apply_responsive_card_heights()

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
        self._geometry_settings_key = "glass_soundboard_geometry"
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(550)
        self._geometry_save_timer.timeout.connect(self._save_geometry_now)

        self.setWindowTitle("K-Sounds Soundboard")
        self.setMinimumSize(420, 320)
        _restore_window_geometry(self, self._geometry_settings_key, 720, 520, 420, 320)

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

    def _save_geometry_now(self) -> None:
        _save_window_geometry(self, self._geometry_settings_key)

    def _restore_geometry_after_show(self) -> None:
        _restore_window_geometry(self, self._geometry_settings_key, 720, 520, 420, 320)

    def _queue_geometry_save(self) -> None:
        _queue_window_geometry_save(self, self._geometry_settings_key, self._geometry_save_timer)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._restore_geometry_after_show)
        QTimer.singleShot(350, self._restore_geometry_after_show)

    def closeEvent(self, event) -> None:
        self._save_geometry_now()
        super().closeEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._queue_geometry_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._queue_geometry_save()
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
    def __init__(self, visual_callback=None, backend_controller=None):
        super().__init__()
        self.setObjectName("drawer")
        self.setFixedWidth(358)
        self._visual_callback = visual_callback
        self._backend_controller = backend_controller

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

    def _notify_visual(self, key: str, value) -> None:
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

        root.addWidget(AppsPanel(self._backend_controller))

        return self._make_scroll_page(content)


    def _eq_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("EQ editor")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        root.addWidget(EqPanel(self._backend_controller), 1)

        return self._make_scroll_page(content)


    def _settings_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 4, 2, 4)
        root.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        settings = getattr(self._backend_controller, "settings", None)

        self.show_meters_check = QCheckBox("Show meters")
        self.show_meters_check.setChecked(bool(getattr(settings, "visualizer_enabled", True)))
        self.show_meters_check.toggled.connect(lambda checked: self._notify_visual("meters", bool(checked)))
        root.addWidget(self.show_meters_check)

        self.show_overlay_check = QCheckBox("Show overlay")
        self.show_overlay_check.setChecked(bool(getattr(settings, "overlay_enabled", False)))
        self.show_overlay_check.toggled.connect(lambda checked: self._notify_visual("overlay", bool(checked)))
        root.addWidget(self.show_overlay_check)

        self.close_to_tray_check = QCheckBox("Close to tray")
        self.close_to_tray_check.setChecked(bool(getattr(settings, "close_to_tray", True)))
        self.close_to_tray_check.toggled.connect(lambda checked: self._notify_visual("close_to_tray", bool(checked)))
        root.addWidget(self.close_to_tray_check)

        self.background_enabled_check = QCheckBox("Use custom background")
        self.background_enabled_check.setChecked(bool(getattr(settings, "wallpaper_enabled", False)))
        self.background_enabled_check.toggled.connect(lambda checked: self._notify_visual("background_enabled", bool(checked)))
        root.addWidget(self.background_enabled_check)

        bg_row = QHBoxLayout()
        choose_bg = QPushButton("Change background")
        choose_bg.setObjectName("padTopButton")
        choose_bg.clicked.connect(self._choose_background)
        bg_row.addWidget(choose_bg)

        wallpaper_path = str(getattr(settings, "wallpaper_path", "") or "")
        self.background_path_label = QLabel(Path(wallpaper_path).name if wallpaper_path else "Default background")
        self.background_path_label.setObjectName("muted")
        self.background_path_label.setWordWrap(True)
        bg_row.addWidget(self.background_path_label, 1)
        root.addLayout(bg_row)

        slider_controls = [
            ("Background blur", "blur", int(getattr(settings, "glass_background_blur", 18))),
            ("Background saturation", "saturation", int(getattr(settings, "glass_background_saturation", 72))),
            ("Background darkness", "darkness", int(getattr(settings, "glass_background_darkness", 55))),
            ("Black glass opacity", "glass", int(getattr(settings, "glass_opacity", 70))),
        ]

        for label, key, value in slider_controls:
            root.addWidget(QLabel(label))
            slider = NoWheelSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(max(0, min(100, int(value))))
            slider.setMinimumHeight(34)
            slider.setMaximumHeight(34)
            slider.setTracking(True)
            slider.valueChanged.connect(lambda new_value, item_key=key: self._notify_visual(item_key, int(new_value)))
            root.addWidget(slider)

        root.addStretch(1)
        return self._make_scroll_page(content)

    def _choose_background(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose background",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not path:
            return

        self.background_path_label.setText(Path(path).name)
        self.background_enabled_check.blockSignals(True)
        self.background_enabled_check.setChecked(True)
        self.background_enabled_check.blockSignals(False)
        self._notify_visual("background_path", path)


    def _pads_page(self) -> QWidget:
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("sectionHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        title = QLabel("Soundboard")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        self.pads_panel = PadsPanel(detach_callback=self._detach_pads, columns=3)

        self.pads_analyze_button = QPushButton("↻")
        self.pads_analyze_button.setObjectName("soundboardAnalyzeButton")
        self.pads_analyze_button.setCursor(Qt.PointingHandCursor)
        self.pads_analyze_button.setToolTip("Refresh auto-level analysis for all present soundboard files.")
        self.pads_analyze_button.clicked.connect(self.pads_panel._analyze_soundboard_auto_level)
        self.pads_panel.soundboard_analyze_button = self.pads_analyze_button
        header_layout.addWidget(self.pads_analyze_button, 0, Qt.AlignRight)

        root.addWidget(header)
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


    def _glass_activation_file(self):
        return Path.home() / ".cache" / "k-sounds-hub" / "glass.activate"

    def _close_to_tray_enabled(self) -> bool:
        try:
            backend = getattr(self, "backend_controller", None)
            settings = getattr(backend, "settings", None)
            if settings is not None:
                return bool(getattr(settings, "close_to_tray", False))
        except Exception:
            pass

        try:
            path = Path.home() / ".config" / "k-sounds-hub" / "settings.json"
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                return bool(data.get("close_to_tray", False))
        except Exception:
            pass

        return False

    def _set_tray_visible_for_state(self) -> None:
        try:
            tray = getattr(self, "tray_icon", None)
            if tray is not None:
                tray.setVisible(self._close_to_tray_enabled())
        except Exception:
            pass

    def _focus_existing_window(self) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
        except Exception:
            pass

        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _setup_external_activation(self) -> None:
        try:
            path = self._glass_activation_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

            watcher = QFileSystemWatcher([str(path)], self)
            watcher.fileChanged.connect(self._handle_external_activation)
            self._activation_watcher = watcher
        except Exception:
            pass

    def _handle_external_activation(self, _path: str = "") -> None:
        try:
            path = self._glass_activation_file()
            path.touch(exist_ok=True)

            watcher = getattr(self, "_activation_watcher", None)
            if watcher is not None and str(path) not in watcher.files():
                watcher.addPath(str(path))
        except Exception:
            pass

        self._focus_existing_window()

    def _save_detached_pads_window_geometry(self) -> None:
        try:
            drawer = getattr(self, "drawer", None)
            window = getattr(drawer, "_detached_pads_window", None)
            if window is None:
                return

            save = getattr(window, "_save_geometry_now", None)
            if callable(save):
                save()
        except Exception:
            pass

    def _save_all_window_geometry_now(self) -> None:
        self._save_geometry_now()
        self._save_detached_pads_window_geometry()

    def _shutdown_window_runtime(self) -> None:
        self._save_all_window_geometry_now()

        try:
            tray = getattr(self, "tray_icon", None)
            if tray is not None:
                tray.hide()
        except Exception:
            pass

        try:
            overlay = getattr(self, "overlay", None)
            if overlay is not None:
                shutdown = getattr(overlay, "shutdown", None)
                if callable(shutdown):
                    shutdown()
                else:
                    overlay.close()
        except Exception:
            pass

        try:
            backend = getattr(self, "backend_controller", None)
            if backend is not None:
                backend.shutdown()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self._save_all_window_geometry_now()

        if self._close_to_tray_enabled():
            try:
                self.hide()
                tray = getattr(self, "tray_icon", None)
                if tray is not None:
                    tray.show()
            except Exception:
                pass
            event.ignore()
            return

        self._shutdown_window_runtime()
        event.accept()

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def changeEvent(self, event) -> None:
        # Normal minimize: never force-show the window here.
        try:
            super().changeEvent(event)
        except Exception:
            pass

        try:
            if event.type() == QEvent.WindowStateChange:
                self._set_tray_visible_for_state()
        except Exception:
            pass

    def __init__(self):
        super().__init__()
        self.setWindowTitle("K-Sounds Hub")
        self._geometry_settings_key = "glass_hub_geometry"
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(550)
        self._geometry_save_timer.timeout.connect(self._save_geometry_now)
        # KSH_WINDOW_POLICY_DEDUPED
        QTimer.singleShot(0, self._setup_external_activation)
        QTimer.singleShot(300, self._set_tray_visible_for_state)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(860, 430)
        _restore_window_geometry(self, self._geometry_settings_key, 1320, 560, 860, 430)

        if APP_ICON.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._allow_real_close = False
        self.tray_icon: QSystemTrayIcon | None = None

        self._background_source = QPixmap(str(APP_BG)) if APP_BG.is_file() else QPixmap()
        self._background_saturation = 0.72
        self._background_darkness = 130
        self._glass_opacity = 178
        self._meter_phase = 0.0
        self._settings_sync_mtime_ns = 0
        self.backend_controller = GlassBackendController(self)
        self._load_visual_settings_from_backend()
        self.backend_controller.channel_state_changed.connect(self._sync_channel_card_from_backend)
        self._device_watch_signature: tuple = ()

        self.overlay = OverlayManager(self)
        self.overlay.set_enabled(bool(getattr(self.backend_controller.settings, "overlay_enabled", False)))
        self.backend_controller.overlay_message_requested.connect(self._show_overlay_message)
        self._setup_tray_icon()

        self.channel_cards: list[ChannelCard] = []

        self._background_refresh_timer = QTimer(self)
        self._background_refresh_timer.setSingleShot(True)
        self._background_refresh_timer.setInterval(80)
        self._background_refresh_timer.timeout.connect(self._refresh_background_now)

        self._visual_style_timer = QTimer(self)
        self._visual_style_timer.setSingleShot(True)
        self._visual_style_timer.setInterval(24)
        self._visual_style_timer.timeout.connect(self._apply_visual_style)

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
        self.background_blur.setBlurRadius(float(getattr(self.backend_controller.settings, "glass_background_blur", 18)))
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
            card_devices = self._channel_device_choices(channel_key, devices)
            card = ChannelCard(
                name,
                icon,
                card_devices,
                value,
                channel_key,
                volume_callback=self._send_channel_volume,
                mute_callback=self._set_channel_muted,
                device_callback=self._set_channel_device,
                current_device=self._channel_device_label(channel_key, card_devices),
            )
            card.sync_from_saved_state(volume=value, muted=muted)
            self.channel_cards.append(card)
            cards_row.addWidget(card)

        content_layout.addLayout(cards_row, 1)
        self._set_meters_visible(bool(getattr(self.backend_controller.settings, "visualizer_enabled", True)))

        self.drawer = Drawer(self._apply_visual_setting, self.backend_controller)
        self.drawer.setVisible(False)
        content_layout.addWidget(self.drawer)

        self.nav_group.idClicked.connect(self._on_nav_clicked)

        self._install_resize_event_filter()
        self._apply_visual_style()
        self._refresh_background()
        self._start_meter_simulation()
        self._device_watch_debounce = QTimer(self)
        self._device_watch_debounce.setSingleShot(True)
        self._device_watch_debounce.setInterval(300)
        self._device_watch_debounce.timeout.connect(lambda: self._refresh_device_selectors_if_needed(force=True))

        self._device_watch_process = QProcess(self)
        self._device_watch_process.setProgram("pactl")
        self._device_watch_process.setArguments(["subscribe"])
        self._device_watch_process.readyReadStandardOutput.connect(self._handle_device_watch_events)
        self._device_watch_process.finished.connect(self._handle_device_watch_finished)
        self._device_watch_process.errorOccurred.connect(
            lambda _error: self.backend_controller.status_changed.emit("Audio device watcher unavailable")
        )
        if __import__("os").environ.get("KSH_DEVICE_WATCHER_DISABLED", "").strip() != "1":
            QTimer.singleShot(0, self._start_device_watch_process)
            QTimer.singleShot(0, lambda: self._refresh_device_selectors_if_needed(force=True))
        QTimer.singleShot(450, self.backend_controller.normalize_channel_playback_routes)

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

    def _setup_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        tray = QSystemTrayIcon(self)
        if APP_ICON.is_file():
            tray.setIcon(QIcon(str(APP_ICON)))
        elif not self.windowIcon().isNull():
            tray.setIcon(self.windowIcon())

        tray.setToolTip("K-Sounds Hub")

        menu = QMenu(self)

        show_action = menu.addAction("Show K-Sounds Hub")
        show_action.triggered.connect(self._restore_from_tray)

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit_from_tray)

        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()

        self.tray_icon = tray

    def _tray_activated(self, reason) -> None:
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        if self.tray_icon is not None:
            try:
                self.tray_icon.show()
            except Exception:
                pass

        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._allow_real_close = True
        self._save_all_window_geometry_now()
        if self.tray_icon is not None:
            try:
                self.tray_icon.hide()
            except Exception:
                pass
        self.close()

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def _on_nav_clicked(self, idx: int) -> None:
        if idx == 0:
            self.drawer.setVisible(False)
            return
        self.drawer.setVisible(True)
        self.drawer.show_page(idx - 1)

    def _save_visual_settings_later(self) -> None:
        timer = getattr(self.backend_controller, "_save_timer", None)
        if timer is not None:
            timer.start()

    def _load_background_source_from_settings(self) -> QPixmap:
        settings = self.backend_controller.settings
        if bool(getattr(settings, "wallpaper_enabled", False)):
            path = Path(str(getattr(settings, "wallpaper_path", "") or "")).expanduser()
            if path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap
        return QPixmap(str(APP_BG)) if APP_BG.is_file() else QPixmap()

    def _load_visual_settings_from_backend(self) -> None:
        settings = self.backend_controller.settings
        self._background_source = self._load_background_source_from_settings()
        self._background_saturation = max(0.0, min(2.0, float(getattr(settings, "glass_background_saturation", 72)) / 100.0))
        self._background_darkness = int(40 + max(0, min(100, int(getattr(settings, "glass_background_darkness", 55)))) * 2.0)
        self._glass_opacity = int(70 + max(0, min(100, int(getattr(settings, "glass_opacity", 70)))) * 1.55)

        if hasattr(self, "background_blur"):
            self.background_blur.setBlurRadius(float(max(0, min(100, int(getattr(settings, "glass_background_blur", 18))))))

        if hasattr(self, "overlay"):
            self.overlay.set_enabled(bool(getattr(settings, "overlay_enabled", False)))

        self._set_meters_visible(bool(getattr(settings, "visualizer_enabled", True)))

    def _set_meters_visible(self, visible: bool) -> None:
        for card in getattr(self, "channel_cards", []):
            setter = getattr(card, "set_meters_visible", None)
            if callable(setter):
                setter(bool(visible))

    def _apply_visual_setting(self, key: str, value) -> None:
        settings = self.backend_controller.settings
        key = str(key or "").strip().lower()

        if key == "meters":
            settings.visualizer_enabled = bool(value)
            self._set_meters_visible(settings.visualizer_enabled)
            self._save_visual_settings_later()
            return

        if key == "overlay":
            settings.overlay_enabled = bool(value)
            self.overlay.set_enabled(settings.overlay_enabled)
            self._save_visual_settings_later()
            return

        if key == "close_to_tray":
            settings.close_to_tray = bool(value)
            self._save_visual_settings_later()
            return

        if key == "background_enabled":
            settings.wallpaper_enabled = bool(value)
            self._background_source = self._load_background_source_from_settings()
            self._refresh_background()
            self._save_visual_settings_later()
            return

        if key == "background_path":
            settings.wallpaper_path = str(value or "")
            settings.wallpaper_enabled = bool(settings.wallpaper_path)
            self._background_source = self._load_background_source_from_settings()
            self._refresh_background()
            self._save_visual_settings_later()
            return

        try:
            numeric = max(0, min(100, int(value)))
        except Exception:
            return

        if key == "blur":
            settings.glass_background_blur = numeric
            self.background_blur.setBlurRadius(float(numeric))
            self._save_visual_settings_later()
            return

        if key == "saturation":
            settings.glass_background_saturation = numeric
            self._background_saturation = max(0.0, min(2.0, numeric / 100.0))
            self._request_visual_style_update()
            self._save_visual_settings_later()
            return

        if key == "darkness":
            settings.glass_background_darkness = numeric
            self._background_darkness = int(40 + numeric * 2.0)
            self._request_visual_style_update()
            self._save_visual_settings_later()
            return

        if key == "glass":
            settings.glass_opacity = numeric
            self._glass_opacity = int(70 + numeric * 1.55)
            self._request_visual_style_update()
            self._save_visual_settings_later()
            return


    def _request_visual_style_update(self) -> None:
        timer = getattr(self, "_visual_style_timer", None)
        if timer is not None:
            timer.start()
        else:
            self._apply_visual_style()

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
        if app is not None and app.styleSheet() != STYLE:
            # Keep the static stylesheet application-wide, but avoid rebuilding
            # the whole app stylesheet for every visual slider tick.
            app.setStyleSheet(STYLE)

        # Dynamic glass/background colors only need to affect this window tree.
        self.setStyleSheet(dynamic_style)

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

    def _show_overlay_message(self, text: str, muted_active: bool = False) -> None:
        self.overlay.set_enabled(bool(getattr(self.backend_controller.settings, "overlay_enabled", False)))
        self.overlay.show_message(str(text or ""), muted_active=bool(muted_active))

    def _start_device_watch_process(self) -> None:
        process = getattr(self, "_device_watch_process", None)
        if process is None:
            return
        try:
            if process.state() != QProcess.ProcessState.NotRunning:
                return
            process.start()
        except Exception as exc:
            self.backend_controller.status_changed.emit(f"Audio device watcher unavailable — {exc}")

    def _handle_device_watch_finished(self, *_args) -> None:
        # pactl subscribe should normally stay alive. If Pulse/PipeWire restarts,
        # retry without falling back to periodic polling.
        QTimer.singleShot(2000, self._start_device_watch_process)

    def _handle_device_watch_events(self) -> None:
        process = getattr(self, "_device_watch_process", None)
        if process is None:
            return

        try:
            data = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        except Exception:
            return

        interesting = False
        for line in data.lower().splitlines():
            # Keep this passive watcher focused on real device topology changes.
            # Do not refresh selectors for sink-input/source-output app stream events.
            if (
                " on sink #" in line
                or " on source #" in line
                or " on card #" in line
                or " on server" in line
            ):
                interesting = True
                break

        if interesting:
            self._device_watch_debounce.start()

    def _device_watch_current_signature(self) -> tuple:
        output_pairs = tuple(self.backend_controller.available_output_targets())
        input_pairs = tuple(self.backend_controller.available_input_targets())
        channel_targets = tuple(
            (str(channel[4]), self.backend_controller.channel_primary_target(str(channel[4])))
            for channel in CHANNELS
        )
        return output_pairs, input_pairs, channel_targets

    def _refresh_device_selectors_if_needed(self, force: bool = False) -> None:
        if self.backend_controller is None or not getattr(self, "channel_cards", None):
            return

        try:
            signature = self._device_watch_current_signature()
        except Exception as exc:
            self.backend_controller.status_changed.emit(f"Device watcher error — {exc}")
            return

        if not force and signature == self._device_watch_signature:
            return

        first_run = not bool(self._device_watch_signature)
        self._device_watch_signature = signature

        cards_by_key = {
            str(getattr(card, "channel_key", "") or "").strip(): card
            for card in self.channel_cards
        }

        for channel in CHANNELS:
            _name, _icon, fallback_devices, _fallback_value, channel_key = channel
            key = str(channel_key or "").strip()
            card = cards_by_key.get(key)
            if card is None:
                continue
            choices = self._channel_device_choices(key, fallback_devices)
            current = self._channel_device_label(key, choices)
            card.sync_device_choices(choices, current)

        if not first_run:
            self.backend_controller.status_changed.emit("Audio devices updated")

    def _channel_device_pairs(self, channel_key: str) -> list[tuple[str, str]]:
        key = str(channel_key or "").strip()
        if key == "micro":
            return self.backend_controller.available_input_targets()
        return self.backend_controller.available_output_targets()

    def _channel_device_choices(self, channel_key: str, fallback_devices: list[str]) -> list[str]:
        key = str(channel_key or "").strip()
        pairs = self._channel_device_pairs(key)
        labels = [label for label, _name in pairs if str(label or "").strip()]

        target = self.backend_controller.channel_primary_target(key)
        if target and not any(name == target for _label, name in pairs):
            label = self.backend_controller.label_for_target(target, input_device=(key == "micro")) or target
            missing_label = _format_missing_device_label(label)
            if missing_label not in labels:
                labels.insert(0, missing_label)

        return labels or list(fallback_devices or [])

    def _channel_device_label(self, channel_key: str, fallback_devices: list[str]) -> str:
        key = str(channel_key or "").strip()
        target = self.backend_controller.channel_primary_target(key)

        if target:
            pairs = self._channel_device_pairs(key)
            label = self.backend_controller.label_for_target(target, input_device=(key == "micro")) or target
            if any(name == target for _label, name in pairs):
                return label
            return _format_missing_device_label(label)

        return fallback_devices[0] if fallback_devices else ""

    def _set_channel_device(self, channel_key: str, label: str) -> None:
        key = str(channel_key or "").strip()
        name = str(label or "").strip()

        if _is_missing_device_label(name):
            self.backend_controller.status_changed.emit(f"Device not found: {_plain_missing_device_label(name)}")
            return

        if key == "micro":
            target = self.backend_controller.resolve_input_label(name)
        else:
            target = self.backend_controller.resolve_output_label(name)

        if not target:
            self.backend_controller.status_changed.emit(f"Unsupported device route: {key} → {name}")
            return

        self.backend_controller.set_channel_primary_target(key, target)

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
        if __import__("os").environ.get("KSH_METERS_DISABLED", "").strip() == "1":
            self.meter_timer = QTimer(self)
            self.meter_timer.setInterval(1000000)
            return

        env = __import__("os").environ
        try:
            interval_ms = int(env.get("KSH_METER_INTERVAL_MS", "60") or "60")
        except Exception:
            interval_ms = 120
        interval_ms = max(45, min(500, interval_ms))

        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(interval_ms)
        self.meter_timer.timeout.connect(self._animate_meters)
        self.meter_timer.start()


    def _animate_meters(self) -> None:
        for card in self.channel_cards:
            key = str(getattr(card, "channel_key", "") or "").strip()
            if not key:
                card.set_meter_levels(0.0, 0.0)
                card.tick_meters()
                continue

            left, right = self.backend_controller.meter_levels(key)
            scale = float(GLASS_METER_INPUT_SCALE.get(key, 1.0))
            if scale != 1.0:
                left = max(0.0, min(1.0, float(left) * scale))
                right = max(0.0, min(1.0, float(right) * scale))
            card.set_meter_levels(left, right)
            card.tick_meters()

    def _save_geometry_now(self) -> None:
        _save_window_geometry(self, self._geometry_settings_key)

    def _restore_geometry_after_show(self) -> None:
        _restore_window_geometry(self, self._geometry_settings_key, 1320, 560, 860, 430)

    def _queue_geometry_save(self) -> None:
        _queue_window_geometry_save(self, self._geometry_settings_key, self._geometry_save_timer)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._restore_geometry_after_show)
        QTimer.singleShot(350, self._restore_geometry_after_show)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._queue_geometry_save()

    def resizeEvent(self, event) -> None:
        # Do not rescale/reprocess the background during live resize.
        # QLabel scaledContents keeps the preview responsive.
        super().resizeEvent(event)
        self._queue_geometry_save()

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
    app.setApplicationName("K-Sounds Hub")
    app.setApplicationDisplayName("K-Sounds Hub")
    app.setOrganizationName("K-Sounds")
    app.setDesktopFileName("ksounds-hub")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    window = PreviewWindow()
    app.aboutToQuit.connect(window._save_all_window_geometry_now)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
