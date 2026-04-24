#!/usr/bin/env bash
set -Eeuo pipefail

pkill -TERM -f 'ksound_hub|audio-hud-overlay|start_ksound_hub|start_overlay_bridge|start_legacy_hud|start_ksound_hub_v2|python.*ksound|pipewire -c filter-chain.conf|parec --device=' 2>/dev/null || true
sleep 2
pkill -KILL -f 'ksound_hub|audio-hud-overlay|start_ksound_hub|start_overlay_bridge|start_legacy_hud|start_ksound_hub_v2|python.*ksound|pipewire -c filter-chain.conf|parec --device=' 2>/dev/null || true
sleep 1
