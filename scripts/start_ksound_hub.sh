#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
IPC_SOCKET="/tmp/ksound_hub_audio_$(id -u).sock"

cd "$REPO_DIR"

# python propre
if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="$REPO_DIR/src"

# ---- check instance réelle ----
is_real_instance_running() {
  pgrep -f "ksound_hub.app" >/dev/null 2>&1
}

# ---- restore propre ----
try_restore() {
  "$PYTHON_BIN" - <<PY
import socket, json, os, sys
sock = f"/tmp/ksound_hub_audio_{os.getuid()}.sock"
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.3)
    s.connect(sock)
    s.sendall((json.dumps({"command":"restore"})+"\n").encode())
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
}

# ---- nettoyage agressif mais safe ----
cleanup() {
  rm -f "$IPC_SOCKET" || true
  pkill -f "pipewire -c filter-chain.conf" || true
  pkill -f "parec --device=" || true
}

# ---- logique principale ----
if is_real_instance_running; then
  if try_restore; then
    exit 0
  fi
fi

# si socket existe mais pas de vraie instance → corruption
if [[ -S "$IPC_SOCKET" ]] && ! is_real_instance_running; then
  cleanup
fi

# clean toujours avant start (évite accumulation)
cleanup

# start audio stack
if [[ -x "$HOME/.config/audio-stack/audio-setup.sh" ]]; then
  "$HOME/.config/audio-stack/audio-setup.sh" >/dev/null 2>&1 || true
fi

# HUD
if [[ -x "$REPO_DIR/scripts/start_legacy_hud.sh" ]]; then
  "$REPO_DIR/scripts/start_legacy_hud.sh" >/dev/null 2>&1 || true
fi

# APP (bloquant)
exec "$PYTHON_BIN" -m ksound_hub.app
