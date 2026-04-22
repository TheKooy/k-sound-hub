#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HUD_BIN="/home/kooy/k-sound-hub/tools/legacy_hud/build/audio-hud-overlay"
HUD_LOG="${XDG_RUNTIME_DIR:-/tmp}/ksound-legacy-hud.log"

if [[ ! -x "$HUD_BIN" ]]; then
  exit 0
fi

if pgrep -f "$HUD_BIN" >/dev/null 2>&1; then
  exit 0
fi

cd "$(dirname "$HUD_BIN")"
nohup "$HUD_BIN" >>"$HUD_LOG" 2>&1 &
