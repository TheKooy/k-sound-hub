#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${1:-$HOME/k-sound-hub-v2}"
BIN="$REPO/native_engine/build/ksound_native_engine"
RUNTIME_DIR="$HOME/.config/ksound-hub-v2/runtime/native-engine"
STATE="$RUNTIME_DIR/state.json"
LEVELS="$RUNTIME_DIR/levels.json"
LOG="$RUNTIME_DIR/engine.log"

[[ -x "$BIN" ]] || { echo "Binaire introuvable: $BIN" >&2; exit 1; }
mkdir -p "$RUNTIME_DIR"

cat > "$STATE" <<JSON
{
  "note": "native engine foundation smoke state",
  "timestamp": $(date +%s)
}
JSON

nohup "$BIN" \
  --state "$STATE" \
  --levels "$LEVELS" \
  --log "$LOG" \
  --period-ms 20 \
  >>"$LOG" 2>&1 &

echo "$!"
