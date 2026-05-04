# K-Sound Hub v0.3.1

First public Linux-focused release candidate.

## Highlights

- PipeWire-first Linux audio hub
- fixed channel set: ALL, GAME, CHAT, MEDIA, MORE, MICRO, RETOUR-MIC
- per-channel volume, mute, EQ profile UI, and live meters
- optional overlay feedback
- Android soundboard source included
- non-invasive user installer

## Install

```bash
./install.sh
```

To let the installer install distro packages with sudo:

```bash
./install.sh --install-system-deps
```

## Notes

- No autostart is enabled by default.
- No global PipeWire configuration is written.
- Android APK is optional and should be shipped as a separate release asset when desired.
