# K-Sounds Hub

K-Sounds Hub is a PipeWire-first modular Linux audio hub.

It provides a focused desktop GUI for Linux audio routing, per-channel control, persistent settings, optional overlay feedback, IPC control shortcuts, live level meters, and PipeWire-based app routing helpers.

This project is being developed with AI assistance.

## Status

Current version: 0.3.2

Main tested environment:

- EndeavourOS / Arch Linux
- KDE Plasma / Wayland
- PipeWire
- WirePlumber
- Python 3.11+

Other major Linux distributions are supported on a best-effort basis through the non-invasive installer.

## Features

- fixed channel set: ALL, GAME, CHAT, MEDIA, MORE, MICRO, RETOUR-MIC
- per-channel volume and mute
- per-channel EQ profile selection and editing
- live signal meter widgets
- optional on-screen overlay feedback
- IPC control for external shortcuts
- optional wallpaper/background styling
- tray-capable close behavior
- optional Android soundboard remote source

## Recommended user installation

For normal users, install K-Sounds Hub from the GitHub Releases page.

Important:

- Do not use the green Code button for normal installation.
- Do not download the automatic Source code zip or Source code tar.gz files.
- Download one of the release assets instead:
  - k-sounds-hub-linux-release-v0.3.2.tar.gz
  - k-sounds-hub-linux-release-v0.3.2.zip

### Install from the tar.gz release

Open a terminal in the folder where you downloaded the file, then run:

    tar -xzf k-sounds-hub-linux-release-v0.3.2.tar.gz
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

Then start the app with:

    k-sounds-hub

### Install from the zip release

Open a terminal in the folder where you downloaded the file, then run:

    unzip k-sounds-hub-linux-release-v0.3.2.zip
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

Then start the app with:

    k-sounds-hub

### Notes

- Run install.sh from a terminal, not by double-clicking it in the file manager.
- install.sh installs the app but does not automatically launch it.
- If k-sounds-hub is not found after installation, close and reopen the terminal, or run:

    ~/.local/bin/k-sounds-hub

The default install is intentionally non-invasive.

It installs into:

    ~/.local/share/k-sounds-hub/app
    ~/.local/share/k-sounds-hub/app/.venv
    ~/.local/bin/k-sounds-hub
    ~/.local/share/applications/k-sounds-hub.desktop
    ~/.config/k-sounds-hub

It does not:

- write to /etc
- write to /usr
- write to /opt
- enable autostart
- write global PipeWire configuration
- remove distro packages during uninstall

If required system dependencies are missing, the installer stops and tells you what is missing.

To let the installer install distro packages with sudo:

    ./install.sh --install-system-deps

For non-interactive package installation where supported:

    ./install.sh --install-system-deps --yes

See docs/INSTALL.md for details.

## Uninstall

    ~/.local/share/k-sounds-hub/app/uninstall.sh

Remove saved config too:

    ~/.local/share/k-sounds-hub/app/uninstall.sh --remove-config

## Runtime dependencies

Required commands:

- python3 3.11 or newer
- pactl
- parec
- pw-cat
- ffmpeg

Expected audio stack:

- PipeWire
- PipeWire PulseAudio compatibility
- WirePlumber

Python dependencies are installed into the app-local virtual environment:

- PySide6
- NumPy

## Development installation

For development, clone the repository and use an editable Python install:

    git clone https://github.com/TheKooy/k-sounds-hub.git
    cd k-sounds-hub
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -e .[dev]

Run checks:

    python -m pytest
    ./scripts/check_k_sound_hub_env.sh

Start from the source tree:

    ./scripts/start_ksound_hub_v2.sh

## Packaging a release

Maintainers can create local release archives with:

    ./scripts/package_release.sh

This creates:

    dist/k-sounds-hub-linux-release-vX.Y.Z.tar.gz
    dist/k-sounds-hub-linux-release-vX.Y.Z.zip
    dist/SHA256SUMS.txt

Release archives and APK files should be uploaded as GitHub Release assets, not committed to Git.

See docs/GITHUB_RELEASE.md for details.

## Android soundboard remote

The Android soundboard source is included in the repository.

Generated APK files are optional release assets and should not be committed to Git.

## Repository

Repository: https://github.com/TheKooy/k-sounds-hub

Default public branch: main

Current active development branch: feature/native-micro-engine

## Disclaimer

K-Sounds Hub interacts with the user's Linux audio session through PipeWire/PulseAudio-compatible tools. It is intended to be non-destructive, but it is still audio-routing software. Review scripts before running them on important systems.
