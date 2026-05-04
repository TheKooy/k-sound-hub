# K-Sounds Hub V2 backlog

This file tracks known remaining work after the cleanup.

## Audio / microphone

The current default is still the stable legacy PipeWire loopback mic path:

- `KSH_NATIVE_MIC=0`

Remaining work:

1. Integrate EasyEffects cleanly into the V2 architecture.
2. Restore two distinct microphone monitoring modes:
   - direct / pure mic monitor
   - post-EasyEffects mic monitor
3. Continue investigating the native microphone engine before enabling it by default.

## Runtime cleanup

Current runtime builds are local and ignored:

- `native_engine/build/`
- `tools/legacy_hud/build/`

Future improvement:

- Add explicit rebuild/install commands for native runtime binaries.
- Avoid relying on stale local build directories when preparing a fresh machine.
- Keep `tools/legacy_hud/build/` until a replacement overlay exists.

## Android soundboard

Current signing is automatic and local.

Remaining work:

- Add a short Android remote README if APK distribution/setup becomes frequent.
- Optionally add a clean `install-apk` helper for local ADB deployment.
- Avoid committing generated APKs or signing secrets.

## UI / polish

Known future polish areas:

- Continue UI cleanup after source cleanup is finished.
- Keep labels and new UI/dev text in English.
- Preserve existing overlay behavior until replacement is ready.

## Git / release hygiene

Before pushing or handing off:

1. Run tests.
2. Confirm no dangerous V1 references remain.
3. Confirm `.venv/`, build directories, APK outputs, and keystores are ignored.
4. Create a fresh source handoff archive without local build artifacts or secrets.
