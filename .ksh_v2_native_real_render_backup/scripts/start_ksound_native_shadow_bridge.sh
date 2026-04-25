#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
RUNTIME_DIR="${KSH_CONFIG_DIR:-$HOME/.config/ksound-hub-v2}/runtime/native-engine"
ENGINE_BIN="$REPO_DIR/native_engine/build/ksound_native_engine"
STATE_PATH="$RUNTIME_DIR/state.json"
LEVELS_PATH="$RUNTIME_DIR/levels.json"
LOG_PATH="$RUNTIME_DIR/native-engine.log"
BRIDGE_LOG="$RUNTIME_DIR/native-bridge.log"

mkdir -p "$RUNTIME_DIR"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="$REPO_DIR/src"

if [[ -x "$ENGINE_BIN" ]]; then
  if ! pgrep -u "$(id -u)" -f "$ENGINE_BIN --state $STATE_PATH" >/dev/null 2>&1; then
    nohup env \
      KSH_RUNTIME_ROLE="native_engine_shadow" \
      "$ENGINE_BIN" \
      --state "$STATE_PATH" \
      --levels "$LEVELS_PATH" \
      --log "$LOG_PATH" \
      --period-ms 20 >>"$LOG_PATH" 2>&1 &
  fi
fi

BRIDGE_SCRIPT="$REPO_DIR/src/ksound_hub/audio/native_state_bridge.py"
if [[ -f "$BRIDGE_SCRIPT" ]]; then
  if ! pgrep -u "$(id -u)" -f "$BRIDGE_SCRIPT" >/dev/null 2>&1; then
    nohup env \
      KSH_RUNTIME_ROLE="native_engine_bridge" \
      KSH_CONFIG_DIR="${KSH_CONFIG_DIR:-$HOME/.config/ksound-hub-v2}" \
      "$PYTHON_BIN" "$BRIDGE_SCRIPT" >>"$BRIDGE_LOG" 2>&1 &
  fi
fi
