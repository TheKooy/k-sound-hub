#!/usr/bin/env bash
set -Eeuo pipefail

# K-Sound runtime only. Keep patterns explicit enough to avoid touching unrelated audio apps.
KSH_PATTERNS=(
  'ksound_hub'
  'audio-hud-overlay'
  'start_ksound_hub'
  'start_overlay_bridge'
  'start_legacy_hud'
  'start_ksound_hub_v2'
  'python.*ksound'
  'pipewire -c filter-chain.conf'
  'ksound_native_engine'
  'ksound_native_micro_engine'
  'parec --device='
  'pacat --playback --device=micro_bus'
)

for sig in TERM KILL; do
  for pattern in "${KSH_PATTERNS[@]}"; do
    pkill "-$sig" -f "$pattern" 2>/dev/null || true
  done
  [[ "$sig" == "TERM" ]] && sleep 2
done

sleep 1
