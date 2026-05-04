from __future__ import annotations

from pathlib import Path
import os

def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default

_profile_suffix = os.environ.get("KSH_PROFILE_SUFFIX", "").strip()
_default_app_name = "K-Sounds Hub" + (f" {_profile_suffix}" if _profile_suffix else "")
APP_NAME = os.environ.get("KSH_APP_NAME", _default_app_name)
APP_VERSION = "0.3.2"
ORG_NAME = os.environ.get("KSH_ORG_NAME", APP_NAME)
ORG_DOMAIN = os.environ.get("KSH_ORG_DOMAIN", "local.ksoundshub")

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
APP_ICON_PATH = ASSETS_DIR / "app_icon.png"

CONFIG_DIR = _env_path("KSH_CONFIG_DIR", Path.home() / ".config" / "k-sounds-hub")
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LOG_DIR = CONFIG_DIR / "logs"
RUNTIME_DIR = CONFIG_DIR / "runtime"

HUD_SHARED_STATE_DIR = _env_path(
    "KSH_HUD_STATE_DIR",
    Path.home() / ".config" / "audio-stack" / "hud_overlay",
)
HUD_SHARED_STATE_PATH = HUD_SHARED_STATE_DIR / "state.json"
HUD_SHARED_CONFIG_PATH = HUD_SHARED_STATE_DIR / "config.ini"

IPC_SOCKET_PATH = os.environ.get(
    "KSH_IPC_SOCKET_PATH",
    f"/tmp/ksounds_hub_audio_{os.getuid()}.sock",
)

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
