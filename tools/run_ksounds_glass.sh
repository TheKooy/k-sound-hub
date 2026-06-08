#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

PYBIN="$APP_DIR/.venv/bin/python"
if [[ ! -x "$PYBIN" ]]; then
  PYBIN="$(command -v python3)"
fi

ACTIVATE_FILE="$HOME/.cache/k-sounds-hub/glass.activate"
FORCE_RESTART=0
if [[ "${1:-}" == "--force" || "${KSH_GLASS_FORCE_RESTART:-0}" == "1" ]]; then
  FORCE_RESTART=1
fi

mapfile -t OLD_PIDS < <(pgrep -f "$APP_DIR/.venv/bin/python -m ksound_hub.glass_app|python -m ksound_hub.glass_app" || true)

if (( ${#OLD_PIDS[@]} > 0 )) && (( FORCE_RESTART == 0 )); then
  mkdir -p "$(dirname "$ACTIVATE_FILE")"
  date +%s%N > "$ACTIVATE_FILE"
  echo "K-Sounds Hub Glass is already running: PID ${OLD_PIDS[0]}"
  echo "Requested focus for the existing window."
  exit 0
fi

if (( ${#OLD_PIDS[@]} > 0 )) && (( FORCE_RESTART == 1 )); then
  echo "Force restarting Glass instance(s): ${OLD_PIDS[*]}"
  for pid in "${OLD_PIDS[@]}"; do
    [[ "$pid" == "$$" || "$pid" == "$BASHPID" ]] && continue
    kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 0.8
  for pid in "${OLD_PIDS[@]}"; do
    [[ "$pid" == "$$" || "$pid" == "$BASHPID" ]] && continue
    kill -KILL "$pid" 2>/dev/null || true
  done
fi

export PYTHONPATH="$APP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYBIN" -m ksound_hub.glass_app
