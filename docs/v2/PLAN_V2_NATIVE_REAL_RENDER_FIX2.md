# K-Sound Hub V2 – Native Real Render Fix 2

This fixes the broken Fix 1 deployment.

## Root cause of Fix 1 failure

Fix 1 only replaced `pipewire_v2_final.py`, so the repo kept rebuilding the small native-engine foundation binary instead of the real native audio engine from the full native-real-render tranche.

## What Fix 2 does

- copies the full native-real-render engine sources back into `~/k-sound-hub-v2/native_engine/`
- keeps the corrected binary path in `pipewire_v2_final.py` (`parents[3]`)
- rebuilds the real native audio engine
- restarts V2 cleanly

## Expected process state

You should see:
- `ksound_native_engine`
- `parec --device=...monitor`
- `pacat --playback`
- no `v2_final_mixer.py`
- no `native_state_bridge.py`
