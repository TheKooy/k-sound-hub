# K-Sounds Hub V2

This document describes the current V2 state of the project.

Older tranche/fix notes were removed from the working tree because they described obsolete intermediate states. They remain available in Git history.

## Current runtime shape

K-Sounds Hub V2 is the active project. The old `~/k-sounds-hub` V1 tree is obsolete and should not be used.

Current paths:

- Repo: `~/k-sound-hub-v2`
- Config: `~/.config/k-sounds-hub`
- IPC socket: `/tmp/ksound_hub_audio_v2_<uid>.sock`
- Launcher: `scripts/start_ksound_hub_v2.sh`
- Clean start wrapper: `~/.local/bin/start_ksound_v2_clean.sh`

## Main app

- Python / PySide6 app package: `ksound_hub`
- Main entry point: `python -m ksound_hub.app`
- Control entry point: `python -m ksound_hub.control`
- Main launcher script: `scripts/start_ksound_hub_v2.sh`
- Installed launcher wrapper: `~/.local/bin/start_ksound_v2_clean.sh`

## Playback channels

Visible playback channels:

- `all`
- `game`
- `chat`
- `media`
- `more`

Extra channels:

- `micro`
- `return-mic`

## Playback architecture

The current playback render path uses the native C++ engine:

- `native_engine/build/ksound_native_engine`

The engine reads runtime state from:

- `~/.config/k-sounds-hub/runtime/native-engine/`

It owns the current final playback render path.

The cleanup removed obsolete Python playback prototypes from the source tree. Those old files remain available in Git history.

## Overlay

The current overlay binary is:

- `tools/legacy_hud/build/audio-hud-overlay`

The `legacy_hud` name is historical. The binary is still part of the current runtime and should not be deleted unless a replacement overlay exists.

## Android soundboard remote

Android remote source:

- `android-soundboard-apk/`

PC web/pairing side:

- `tools/soundboard_remote/`

APK signing is local and automatic. The repo must not contain signing secrets.

Default local signing files:

- `~/.local/share/k-sounds-hub/android/ksound-soundboard.keystore`
- `~/.local/share/k-sounds-hub/android/signing.env`

The APK build script can generate a local keystore automatically if none exists:

- `scripts/build_android_soundboard_apk.sh`

Optional overrides:

- `KSOUND_SOUNDBOARD_SIGN_DIR`
- `KSOUND_SOUNDBOARD_KEYSTORE`

## Local files intentionally ignored

These are expected to stay local and ignored by Git:

- `.venv/`
- `native_engine/build/`
- `tools/legacy_hud/build/`
- `dist/`
- `android-soundboard-apk/gen/`
- `android-soundboard-apk/classes/`
- `android-soundboard-apk/dex/`
- `android-soundboard-apk/*.apk`
- `android-soundboard-apk/*.keystore`
- `android-soundboard-apk/*.jks`

## Cleanup status

Completed:

- V1 launch fallbacks removed from source.
- Installed V1 launchers removed.
- Old `~/k-sounds-hub` tree archived and removed.
- Old `~/.config/ksound-hub` config archived and removed.
- Tracked `.venv` symlink removed from Git.
- V2 now uses a real local `.venv/`.
- Obsolete Python audio prototypes removed.
- Android keystore moved out of repo.
- Android signing made automatic and local.
