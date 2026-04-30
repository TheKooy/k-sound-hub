#!/usr/bin/env python3
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ksound-hub-v2"
PAIRING_PATH = CONFIG_DIR / "soundboard_pairing.json"
TOKEN_PATH = CONFIG_DIR / "soundboard_web_token"
PORT = 8765
TTL_SECONDS = 300

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

pin = f"{secrets.randbelow(1_000_000):06d}"
expires_at = time.time() + TTL_SECONDS

PAIRING_PATH.write_text(
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
PAIRING_PATH.chmod(0o600)

print()
print("K-Sound Soundboard Pairing")
print("==========================")
print(f"Code Android : {pin}")
print(f"Expire dans  : {TTL_SECONDS // 60} minutes")
print()
print("Ouvre l'app Android K-Sound Soundboard.")
print("Elle doit découvrir le PC automatiquement, puis demande ce code.")
print()
