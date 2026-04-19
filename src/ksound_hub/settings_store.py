from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIG_DIR, SETTINGS_PATH
from .models import AppSettings


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.is_file():
            return AppSettings.default()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return AppSettings.default()

        if not isinstance(data, dict):
            return AppSettings.default()

        return AppSettings.from_dict(data)

    def save(self, settings: AppSettings) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = settings.to_dict()
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
