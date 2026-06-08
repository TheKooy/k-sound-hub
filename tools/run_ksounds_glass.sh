#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

PYBIN="$APP_DIR/.venv/bin/python"
if [[ ! -x "$PYBIN" ]]; then
  PYBIN="$(command -v python3)"
fi

ACTIVATE_FILE="$HOME/.cache/k-sounds-hub/glass.activate"

mapfile -t OLD_PIDS < <(pgrep -f "$APP_DIR/.venv/bin/python -m ksound_hub.glass_app|python -m ksound_hub.glass_app" || true)

if (( ${#OLD_PIDS[@]} > 0 )); then
  mkdir -p "$(dirname "$ACTIVATE_FILE")"
  date +%s%N > "$ACTIVATE_FILE"
  echo "K-Sounds Hub Glass is already running: PID ${OLD_PIDS[0]}"
  echo "Requested focus for the existing window."
  exit 0
fi

export PYTHONPATH="$APP_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYBIN" -m ksound_hub.glass_app
