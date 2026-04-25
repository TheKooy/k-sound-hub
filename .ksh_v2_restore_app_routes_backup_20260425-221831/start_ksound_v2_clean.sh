#!/usr/bin/env bash
set -Eeuo pipefail

kill_matches() {
  local pattern="$1"
  local sig="${2:-TERM}"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    local pid="${line%% *}"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$pid" -eq "$$" ]] && continue
    [[ "$pid" -eq "$PPID" ]] && continue
    kill "-$sig" "$pid" 2>/dev/null || true
  done < <(pgrep -af "$pattern" || true)
}

echo "===== STOP V1 + V2 + AUDIO RUNTIME ====="
kill_matches "$HOME/k-sound-hub/.venv/bin/python -m ksound_hub.app" TERM
kill_matches "$HOME/k-sound-hub-v2/.venv/bin/python -m ksound_hub.app" TERM
kill_matches "$HOME/k-sound-hub/tools/legacy_hud/build/audio-hud-overlay" TERM
kill_matches "$HOME/k-sound-hub-v2/tools/legacy_hud/build/audio-hud-overlay" TERM
kill_matches "$HOME/k-sound-hub-v2/native_engine/build/ksound_native_engine" TERM
kill_matches "native_state_bridge.py" TERM
kill_matches 'v2_final_mixer.py' TERM
kill_matches 'pipewire -c filter-chain.conf' TERM
kill_matches 'parec --device=' TERM
kill_matches 'pacat --playback' TERM
sleep 2
kill_matches "$HOME/k-sound-hub/.venv/bin/python -m ksound_hub.app" KILL
kill_matches "$HOME/k-sound-hub-v2/.venv/bin/python -m ksound_hub.app" KILL
kill_matches "$HOME/k-sound-hub/tools/legacy_hud/build/audio-hud-overlay" KILL
kill_matches "$HOME/k-sound-hub-v2/tools/legacy_hud/build/audio-hud-overlay" KILL
kill_matches "$HOME/k-sound-hub-v2/native_engine/build/ksound_native_engine" KILL
kill_matches "native_state_bridge.py" KILL
kill_matches 'v2_final_mixer.py' KILL
kill_matches 'pipewire -c filter-chain.conf' KILL
kill_matches 'parec --device=' KILL
kill_matches 'pacat --playback' KILL
sleep 1

echo
echo "===== START K-SOUND HUB V2 ====="
"$HOME/k-sound-hub-v2/scripts/start_ksound_hub_v2.sh" >/tmp/ksound-hub-v2-clean-start.log 2>&1 &
sleep 4

echo
echo "===== PROCESS ====="
pgrep -af "$HOME/k-sound-hub-v2/.venv/bin/python -m ksound_hub.app|$HOME/k-sound-hub-v2/tools/legacy_hud/build/audio-hud-overlay|$HOME/k-sound-hub-v2/native_engine/build/ksound_native_engine|parec --device=|pacat --playback|v2_final_mixer.py|native_state_bridge.py|pipewire -c filter-chain.conf" || true
echo
echo "===== V1 SHOULD BE EMPTY ====="
pgrep -af "$HOME/k-sound-hub/.venv/bin/python -m ksound_hub.app|$HOME/k-sound-hub/tools/legacy_hud/build/audio-hud-overlay" || true
