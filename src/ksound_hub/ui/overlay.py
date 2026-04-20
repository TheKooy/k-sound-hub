from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QObject


class OverlayManager(QObject):
    """
    Pont vers l'ancien overlay Carla Hub.
    On n'essaie plus de recréer un overlay séparé ici :
    on écrit directement dans le même state.json que l'ancien HUD,
    qui est déjà validé visuellement et côté placement.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._seq = 0

        self.legacy_dir = Path.home() / ".config" / "audio-stack" / "hud_overlay"
        self.legacy_state_path = self.legacy_dir / "state.json"
        self.legacy_dir.mkdir(parents=True, exist_ok=True)

        if self.legacy_state_path.is_file():
            try:
                data = json.loads(self.legacy_state_path.read_text(encoding="utf-8"))
                self._seq = int(data.get("seq", 0))
            except Exception:
                self._seq = 0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def show_message(self, text: str, duration_ms: int = 900) -> None:
        if not self._enabled or not text:
            return

        self._seq += 1
        payload = {
            "seq": self._seq,
            "text": text,
            "visible": True,
            "durationMs": int(duration_ms),
            "timestamp": int(time.time() * 1000),
        }

        tmp = self.legacy_state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.legacy_state_path)

    def shutdown(self) -> None:
        # On ne coupe pas l'ancien HUD ici.
        # On laisse le process overlay vivre comme avant.
        pass
