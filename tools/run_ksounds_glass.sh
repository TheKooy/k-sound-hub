#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

PYBIN="$APP_DIR/.venv/bin/python"
if [[ ! -x "$PYBIN" ]]; then
  PYBIN="$(command -v python3)"
fi

echo "K-Sounds Hub Glass launcher"
echo "Repo: $APP_DIR"

mapfile -t OLD_PIDS < <(pgrep -f 'ksound_hub.glass_app' || true)
if (( ${#OLD_PIDS[@]} > 0 )); then
  echo "Stopping stale/hidden Glass instance(s): ${OLD_PIDS[*]}"
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
