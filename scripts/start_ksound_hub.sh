#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
CONFIG_DIR="$HOME/.config/ksound-hub"
RUNTIME_DIR="$CONFIG_DIR/runtime"
IPC_SOCKET="/tmp/ksound_hub_audio_$(id -u).sock"
LOCK_FILE="$RUNTIME_DIR/app.lock"

cd "$REPO_DIR"
mkdir -p "$RUNTIME_DIR"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="$REPO_DIR/src"

is_real_instance_running() {
  pgrep -u "$(id -u)" -f 'python(3)? .* -m ksound_hub\.app|ksound_hub\.app' >/dev/null 2>&1
}

try_restore() {
  "$PYTHON_BIN" - <<'PY'
import json
import os
import socket
import sys

sock = f"/tmp/ksound_hub_audio_{os.getuid()}.sock"
try:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.3)
    client.connect(sock)
    client.sendall((json.dumps({"command": "restore"}) + "\n").encode())
    client.close()
    raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
}

cleanup_stale_runtime_files() {
  rm -f "$IPC_SOCKET" || true
  rm -f "$LOCK_FILE" || true
}

cleanup_managed_processes() {
  "$PYTHON_BIN" - <<'PY'
import os
import signal
import time
from pathlib import Path

TARGET_ROLES = {"eq_slot", "meter_probe"}
uid = os.getuid()
proc_root = Path("/proc")
pids = []

for entry in proc_root.iterdir():
    if not entry.name.isdigit():
        continue
    pid = int(entry.name)
    if pid == os.getpid():
        continue

    status_path = entry / "status"
    environ_path = entry / "environ"
    try:
        status_text = status_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue

    real_uid = None
    for line in status_text.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2:
                real_uid = int(parts[1])
            break
    if real_uid != uid:
        continue

    try:
        environ_raw = environ_path.read_bytes()
    except Exception:
        continue

    env = {}
    for chunk in environ_raw.split(b"\0"):
        if b"=" not in chunk:
            continue
        key, value = chunk.split(b"=", 1)
        env[key.decode("utf-8", errors="ignore")] = value.decode("utf-8", errors="ignore")

    if env.get("KSH_RUNTIME_ROLE") in TARGET_ROLES:
        pids.append(pid)

for sig in (signal.SIGTERM, signal.SIGKILL):
    for pid in list(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except Exception:
            pass
    if sig == signal.SIGTERM and pids:
        time.sleep(1.0)
PY
}

if is_real_instance_running; then
  if try_restore; then
    exit 0
  fi
fi

if [[ -S "$IPC_SOCKET" ]] && ! is_real_instance_running; then
  cleanup_stale_runtime_files
fi

cleanup_managed_processes
cleanup_stale_runtime_files

if [[ -x "$HOME/.config/audio-stack/audio-setup.sh" ]]; then
  "$HOME/.config/audio-stack/audio-setup.sh" >/dev/null 2>&1 || true
fi

if [[ -x "$REPO_DIR/scripts/start_overlay_bridge.sh" ]]; then
  "$REPO_DIR/scripts/start_overlay_bridge.sh" >/dev/null 2>&1 || true
fi

exec "$PYTHON_BIN" -m ksound_hub.app
