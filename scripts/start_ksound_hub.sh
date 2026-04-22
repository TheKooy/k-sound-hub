#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
AUDIO_STACK_SCRIPT="$HOME/.config/audio-stack/audio-setup.sh"
BOOTSTRAP_LOG="${XDG_RUNTIME_DIR:-/tmp}/ksound-hub-bootstrap.log"
IPC_SOCKET="/tmp/ksound_hub_audio_$(id -u).sock"

cd "$REPO_DIR"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

restore_existing_instance() {
  "$PYTHON_BIN" - <<'PY'
import json
import os
import socket
import sys

sock_path = f"/tmp/ksound_hub_audio_{os.getuid()}.sock"
payload = {"command": "restore"}

client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.settimeout(0.35)
try:
    client.connect(sock_path)
    client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
except OSError:
    sys.exit(1)
finally:
    try:
        client.close()
    except Exception:
        pass

sys.exit(0)
PY
}

if [[ -S "$IPC_SOCKET" ]]; then
  if restore_existing_instance; then
    exit 0
  fi
fi

if [[ -x "$AUDIO_STACK_SCRIPT" ]]; then
  "$AUDIO_STACK_SCRIPT" >>"$BOOTSTRAP_LOG" 2>&1 || true
  sleep 1
fi

if [[ -x "$REPO_DIR/scripts/start_legacy_hud.sh" ]]; then
  "$REPO_DIR/scripts/start_legacy_hud.sh" >>"$BOOTSTRAP_LOG" 2>&1 || true
fi

if [[ -x "$REPO_DIR/scripts/install_desktop_entry.sh" ]]; then
  "$REPO_DIR/scripts/install_desktop_entry.sh" --quiet >/dev/null 2>&1 || true
fi

exec "$PYTHON_BIN" -m ksound_hub.app
