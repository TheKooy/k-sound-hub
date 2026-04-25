from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

PLAYBACK_KEYS = {"all", "game", "chat", "media", "more"}
RUNNING = True


def _handle_signal(signum, frame):
    global RUNNING
    RUNNING = False


for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _handle_signal)


def _config_dir() -> Path:
    return Path(os.environ.get("KSH_CONFIG_DIR", str(Path.home() / ".config" / "ksound-hub-v2")))


def _state_path() -> Path:
    return _config_dir() / "runtime" / "native-engine" / "state.json"


def _settings_path() -> Path:
    return _config_dir() / "settings.json"


def _load_settings(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _channel_snapshot(channel: dict) -> dict:
    eq_profiles = channel.get("eq_profiles") or []
    selected_name = channel.get("selected_eq_profile")
    selected = None
    for profile in eq_profiles:
        if profile.get("name") == selected_name:
            selected = profile
            break
    return {
        "key": channel.get("key", ""),
        "enabled": bool(channel.get("enabled", True)),
        "muted": bool(channel.get("muted", False)),
        "volume": int(channel.get("volume", 100) or 100),
        "primary_target": str(channel.get("primary_target", "ANPW") or "ANPW"),
        "selected_eq_profile": selected_name,
        "selected_eq": selected,
        "app_rules": list(channel.get("app_rules") or []),
    }


def _build_state(settings: dict) -> dict:
    channels = []
    for channel in settings.get("channels", []):
        key = str(channel.get("key", ""))
        if key in PLAYBACK_KEYS:
            channels.append(_channel_snapshot(channel))
    return {
        "engine": "native-shadow-bridge",
        "generatedAt": int(time.time() * 1000),
        "channels": channels,
    }


def main() -> int:
    settings_path = _settings_path()
    state_path = _state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    last_digest = ""
    while RUNNING:
        settings = _load_settings(settings_path)
        state = _build_state(settings)
        payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if digest != last_digest:
            tmp = state_path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(state_path)
            last_digest = digest
        time.sleep(0.25)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
