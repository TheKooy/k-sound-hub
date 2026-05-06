#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${KSH_CONFIG_DIR:-$HOME/.config/k-sounds-hub}/runtime"
HUD_LOG="$RUNTIME_DIR/overlay-hud.log"

HUD_BIN="${KSH_HUD_BIN:-}"
if [[ -z "$HUD_BIN" ]]; then
  HUD_BIN="$REPO_DIR/tools/legacy_hud/build/audio-hud-overlay"
fi

mkdir -p "$RUNTIME_DIR"

if [[ ! -x "$HUD_BIN" ]]; then
  exit 0
fi

if pgrep -u "$(id -u)" -f "$HUD_BIN" >/dev/null 2>&1; then
  exit 0
fi

cd "$(dirname "$HUD_BIN")"
nohup env \
  KSH_RUNTIME_ROLE="overlay_bridge_hud" \
  KSH_HUD_BIN="$HUD_BIN" \
  "$HUD_BIN" >>"$HUD_LOG" 2>&1 &
