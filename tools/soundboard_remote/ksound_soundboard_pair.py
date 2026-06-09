#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("KSH_CONFIG_DIR", str(Path.home() / ".config" / "k-sounds-hub"))).expanduser()
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
print("K-Sounds Remote Pairing")
print("==========================")
print(f"Android code: {pin}")
print(f"Expires in: {TTL_SECONDS // 60} minutes")
print()
print("Open the K-Sounds Remote Android app.")
print("It should discover the PC automatically, then ask for this code.")
print()
