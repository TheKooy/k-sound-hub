from pathlib import Path

from ksound_hub.models import AppSettings
from ksound_hub.settings_store import SettingsStore


def test_settings_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    settings = AppSettings.default()
    settings.overlay_enabled = True
    settings.channels[0].volume = 77

    store.save(settings)
    loaded = store.load()

    assert loaded.overlay_enabled is True
    assert loaded.channels[0].volume == 77


def test_close_to_tray_global_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    settings = AppSettings.default()
    settings.close_to_tray = False

    store.save(settings)
    loaded = store.load()

    assert loaded.close_to_tray is False


def test_close_to_tray_legacy_channel_fallback():
    data = {
        "channels": [
            {"key": "all", "name": "ALL", "kind": "playback", "close_to_tray": False},
        ]
    }

    loaded = AppSettings.from_dict(data)

    assert loaded.close_to_tray is False
