from __future__ import annotations

from pathlib import Path
import os

APP_NAME = "K-Sound Hub"
APP_VERSION = "0.3.1"
ORG_NAME = "K-Sound Hub"
ORG_DOMAIN = "local.ksoundhub"

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
APP_ICON_PATH = ASSETS_DIR / "app_icon.png"

CONFIG_DIR = Path.home() / ".config" / "ksound-hub"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LOG_DIR = CONFIG_DIR / "logs"
RUNTIME_DIR = CONFIG_DIR / "runtime"

IPC_SOCKET_PATH = f"/tmp/ksound_hub_audio_{os.getuid()}.sock"

OVERLAY_DURATION_MS = 900
OVERLAY_WIDTH = 380
OVERLAY_HEIGHT = 92
OVERLAY_MARGIN_TOP = 22
OVERLAY_MARGIN_RIGHT = 22
OVERLAY_PANEL_OPACITY = 0.82

DEFAULT_CHANNELS = [
    {"key": "all", "name": "ALL", "enabled": True, "kind": "playback"},
    {"key": "game", "name": "GAME", "enabled": True, "kind": "playback"},
    {"key": "chat", "name": "CHAT", "enabled": True, "kind": "playback"},
    {"key": "media", "name": "MEDIA", "enabled": True, "kind": "playback"},
    {"key": "more", "name": "MORE", "enabled": True, "kind": "playback"},
    {"key": "micro", "name": "MICRO", "enabled": True, "kind": "micro"},
    {"key": "return-mic", "name": "RETOUR-MIC", "enabled": True, "kind": "monitor"},
]

DEFAULT_EQ_BANDS = [
    {"frequency": 60.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 170.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 310.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 600.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 1000.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 3000.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 6000.0, "gain_db": 0.0, "q": 1.0},
    {"frequency": 12000.0, "gain_db": 0.0, "q": 1.0},
]
