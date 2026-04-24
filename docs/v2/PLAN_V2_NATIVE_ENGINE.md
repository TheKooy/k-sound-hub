# K-Sound Hub V2 – Native Engine Foundation

## Objective
Replace the experimental Python final mixer with a real native playback engine foundation that can later own:
- channel ingestion
- per-channel EQ / volume / mute
- per-device final render
- stable real-time scheduling

## What this tranche does
This tranche does **not** replace playback yet.
It installs the native engine subproject and the surrounding tooling into `~/k-sound-hub-v2`:
- `native_engine/` C++ project (CMake)
- `scripts/build_ksound_native_engine.sh`
- `scripts/start_ksound_native_engine.sh`
- `scripts/smoke_test_ksound_native_engine.sh`
- docs and schema notes

It gives you a real buildable/runnable native daemon skeleton with:
- runtime loop
- best-effort RT scheduling
- state-file watching
- heartbeat/levels output
- dedicated log file

## Why this is useful
The previous final-render Python path proved the architecture direction, but not the implementation.
For zero crackle playback, the final render needs a native real-time core.

## What the next tranche would do
- read actual channel routing state
- connect to PipeWire natively
- ingest channel streams without `parec`
- perform native final mix/render
- replace Python final-render in V2

## Scope kept outside this tranche
- micro / return-mic
- UI lag
- GitHub cleanup / release polish
