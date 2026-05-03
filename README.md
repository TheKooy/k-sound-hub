# K-Sound Hub

K-Sound Hub is a PipeWire-first modular Linux audio hub.

It is built for Linux desktop audio routing with a focused GUI, per-channel control, persistent settings, optional wallpaper/background styling, overlay feedback, IPC control shortcuts, live level meters, and PipeWire-based app routing helpers.

> This project is being developed with AI assistance.

## Repository

- Repository: `https://github.com/TheKooy/k-sound-hub`
- Default branch: `main`

## Current target

K-Sound Hub currently targets:

- Linux
- PipeWire
- WirePlumber
- Python 3.11+
- PySide6
- KDE Plasma / Wayland as the main tested environment

The project is installable and runnable as a normal Python application.

## Features currently present

- modular channel UI
- persistent settings
- per-channel volume and mute
- per-channel EQ profile selection and editing
- live signal meter widgets
- optional on-screen overlay feedback
- IPC control for external shortcuts
- optional wallpaper background with blur and dark overlay
- custom app icon support
- tray-capable close behavior
- desktop launcher generation script
- manual autostart support

## Runtime dependencies

Python runtime dependencies:

- `PySide6`
- `numpy`

System commands expected on Linux:

- `pactl`
- `parec`
- `pw-cat`
- `ffmpeg`

PipeWire services expected:

- `pipewire`
- `pipewire-pulse`
- `wireplumber`

## Linux package notes

### Generic Linux

Install these before setting up the Python environment:

- Python 3.11+
- `python-venv` support or equivalent
- `pip`
- PipeWire
- WirePlumber
- PulseAudio compatibility for PipeWire
- `ffmpeg`

Package names vary by distribution.

### Arch / EndeavourOS

Typical packages:

```bash
sudo pacman -S --needed python python-pip python-virtualenv pipewire pipewire-pulse wireplumber ffmpeg
```

If `parec` is missing on the system, also install:

```bash
sudo pacman -S --needed libpulse
```

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/TheKooy/k-sound-hub.git
cd k-sound-hub
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install the Python package and dependencies

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

### 4. Check the local environment

```bash
./scripts/check_k_sound_hub_env.sh
```

This checks:

- required Linux commands
- PipeWire / WirePlumber services
- Python modules used by the app

### 5. Start the application

Recommended launcher:

```bash
./scripts/start_ksound_hub_v2.sh
```

Alternative commands:

```bash
ksound-hub
```

or:

```bash
python -m ksound_hub.app
```

## Desktop launcher

K-Sound Hub does **not** add itself to autostart automatically.

A launcher file can be generated manually from the project with:

```bash
./scripts/install_desktop_entry.sh
```

That installs the launcher into your user applications directory:

```text
~/.local/share/applications/ksound-hub.desktop
```

### Add K-Sound Hub to the application launcher menu

On KDE Plasma or similar desktop environments:

```bash
./scripts/install_desktop_entry.sh
```

Then search for **K-Sound Hub** in the application launcher.

### Create a desktop shortcut

To also copy the launcher to the desktop:

```bash
./scripts/install_desktop_entry.sh --desktop-shortcut
```

## Autostart

K-Sound Hub does **not** enable autostart during installation.

Autostart remains a manual choice.

If autostart is wanted later, use the provided start script:

```bash
$HOME/k-sound-hub-v2/scripts/start_ksound_hub_v2.sh
```

If a desktop-file autostart template is present in the project, adjust its paths manually and place it in the appropriate autostart location for the desktop environment.

## Channel roadmap

The current build ships with the fixed built-in channel set:

- ALL
- GAME
- CHAT
- MEDIA
- MORE
- MICRO
- RETOUR-MIC

Custom channels and extra routing presets are planned, but are not enabled yet in the settings UI.

## Tray behavior

K-Sound Hub supports closing to the system tray instead of fully exiting.

This behavior is controlled from the application settings.

When the setting is enabled:

- clicking the window close button sends the app to the tray
- restoring can be done from the tray icon
- quitting can be done from the tray menu

When the setting is disabled:

- clicking the window close button fully exits the app

## Updating dependencies later

Inside the repository:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

## Development installation

For development tools:

```bash
source .venv/bin/activate
python -m pip install -e .[dev]
```

## Tests

```bash
source .venv/bin/activate
pytest
```

## Repository layout

```text
src/ksound_hub/
  app.py
  config.py
  control.py
  ipc.py
  models.py
  settings_store.py
  assets/
  audio/
  ui/

scripts/
  start_ksound_hub_v2.sh
  check_k_sound_hub_env.sh
  install_desktop_entry.sh

packaging/linux/
  ksound-hub.desktop
  ksound-hub.desktop.template
  ksound-hub-autostart.desktop.template
```

## Recommended install flow on another Linux PC

1. clone the repository
2. create and activate `.venv`
3. install with `python -m pip install -e .`
4. run `./scripts/check_k_sound_hub_env.sh`
5. start with `./scripts/start_ksound_hub_v2.sh`
6. optionally create the launcher with `./scripts/install_desktop_entry.sh`
7. optionally copy the launcher into `~/.local/share/applications/`

## License

MIT License. See `LICENSE`.

## Disclaimer

This software is provided as-is.

It should be tested carefully before being relied on for streaming, voice chat, recording, live routing, or production audio use.
