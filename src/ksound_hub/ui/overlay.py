from __future__ import annotations

import json
import time

from PySide6.QtCore import QObject

from ..config import HUD_SHARED_STATE_DIR, HUD_SHARED_STATE_PATH


class OverlayManager(QObject):
    """
    Bridge vers le HUD overlay actuellement utilisé par K-Sound Hub.

    Le rendu natif reste assuré par le binaire Qt existant.
    Cette classe se contente d'écrire dans le state partagé attendu par ce HUD.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._seq = 0
        self._hud_state_dir = HUD_SHARED_STATE_DIR
        self._hud_state_path = HUD_SHARED_STATE_PATH
        self._hud_state_dir.mkdir(parents=True, exist_ok=True)
        self._seq = self._load_last_sequence()

    def _load_last_sequence(self) -> int:
        if not self._hud_state_path.is_file():
            return 0
        try:
            data = json.loads(self._hud_state_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        try:
            return int(data.get("seq", 0))
        except Exception:
            return 0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def show_message(self, text: str, duration_ms: int = 900, *, muted_active: bool = False) -> None:
        if not self._enabled or not text:
            return

        self._seq += 1
        payload = {
            "seq": self._seq,
            "text": text,
            "visible": True,
            "durationMs": int(duration_ms),
            "mutedActive": bool(muted_active),
            "timestamp": int(time.time() * 1000),
        }

        tmp_path = self._hud_state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self._hud_state_path)

    def shutdown(self) -> None:
        # Le process HUD reste géré séparément par le launcher.
        pass
