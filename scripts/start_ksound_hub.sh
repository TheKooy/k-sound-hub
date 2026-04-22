#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
AUDIO_STACK_SCRIPT="$HOME/.config/audio-stack/audio-setup.sh"
BOOTSTRAP_LOG="${XDG_RUNTIME_DIR:-/tmp}/ksound-hub-bootstrap.log"

cd "$REPO_DIR"

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

export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  exec "$VENV_DIR/bin/python" -m ksound_hub.app
fi

exec python -m ksound_hub.app
