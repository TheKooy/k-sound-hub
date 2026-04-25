# K-Sound Hub V2 – Native Real Render

This tranche replaces the Python final-render playback path with the native C++ engine.

## Goal

Keep the V2 playback architecture:
- visible channels stay `ALL / GAME / CHAT / MEDIA / MORE`
- app routing stays unchanged
- per-channel volume / mute / EQ stay available
- one final render per active physical target

But remove Python from the real-time audio path.

## What changes

- `pipewire_v2_final.py` no longer starts `v2_final_mixer.py`
- it writes a lightweight native render state file
- it starts `native_engine/build/ksound_native_engine`
- the native engine:
  - captures channel monitors with `parec`
  - applies per-channel biquad EQ in C++
  - mixes per active target
  - writes final audio to the target with `pacat`
  - writes `levels.json` for meters

## What stays out of scope

- micro / return-mic logic
- full PipeWire native API integration
- realtime scheduling tuning / RTKit / limits.d finalization

## Success criteria

- V2 still launches normally
- no `v2_final_mixer.py` process remains
- one `ksound_native_engine` process owns playback final render
- playback routing/features still behave like V2 final-render
