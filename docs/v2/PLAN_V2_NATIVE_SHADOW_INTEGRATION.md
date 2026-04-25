# K-Sound Hub V2 – Native Engine Shadow Integration

This tranche does **not** replace playback yet.

It integrates the native engine foundation into the running V2 app lifecycle in a safe way:

- start the native engine automatically with V2 when the binary exists
- run a lightweight Python bridge that mirrors V2 settings into the native engine state file
- keep the current playback path alive as fallback while validating native process management
- ensure restart/cleanup kills native bridge + native engine alongside V2

## What it adds

- `scripts/start_ksound_native_shadow_bridge.sh`
- `src/ksound_hub/audio/native_state_bridge.py`
- patched `scripts/start_ksound_hub_v2.sh`

## Roles

The following runtime roles are managed:

- `native_engine_shadow`
- `native_engine_bridge`

## Validation

After deploy:

- build the native engine if not already built
- launch V2 normally
- verify these processes exist:
  - `ksound_hub.app`
  - `audio-hud-overlay`
  - `ksound_native_engine`
  - `native_state_bridge.py`

## Important

This is a **real integration step**, but not the final playback swap.
The current playback backend stays in place until the native engine is ready to replace it.
