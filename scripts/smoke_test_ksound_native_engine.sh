#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${1:-$HOME/k-sound-hub-v2}"
STARTER="$REPO/scripts/start_ksound_native_engine.sh"
RUNTIME_DIR="${KSH_CONFIG_DIR:-$HOME/.config/k-sounds-hub}/runtime/native-engine"
LEVELS="$RUNTIME_DIR/levels.json"
LOG="$RUNTIME_DIR/engine.log"

[[ -x "$STARTER" ]] || { echo "Starter introuvable: $STARTER" >&2; exit 1; }

PID="$($STARTER "$REPO")"
sleep 2
kill "$PID" 2>/dev/null || true
sleep 1

[[ -f "$LEVELS" ]] || { echo "Levels file introuvable: $LEVELS" >&2; exit 1; }
[[ -f "$LOG" ]] || { echo "Log file introuvable: $LOG" >&2; exit 1; }

echo "===== LEVELS ====="
cat "$LEVELS"
echo
echo "===== LOG ====="
tail -n 20 "$LOG" || true
