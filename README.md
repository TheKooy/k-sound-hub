# K-Sound Hub

K-Sound Hub is a PipeWire-first modular Linux audio hub.

It provides a desktop GUI for managing modular audio channels, persistent settings, live meters, app routing helpers, IPC shortcuts, optional overlay feedback, and optional wallpaper styling.

> This project is being developed with AI assistance.

## Current scope

K-Sound Hub currently targets:

- Linux
- PipeWire
- WirePlumber
- Python 3.11+
- PySide6
- desktop Linux environments with a working system tray and `.desktop` support

KDE Plasma / Wayland is the main tested environment, but the project is intended to remain installable on other Linux distributions as long as the required commands and services are available.

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
- manual desktop launcher support
- manual autostart support

## Runtime requirements

### Python runtime dependencies

- `PySide6`
- `numpy`

### System commands expected on Linux

These commands must be available on the target system:

- `pactl`
- `parec`
- `pw-cat`
- `ffmpeg`

### PipeWire services expected

These user services should be running:

- `pipewire`
- `pipewire-pulse`
- `wireplumber`

## Installation

### 1. Clone the repository

```bash
git clone <YOUR-REPO-URL>
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

### 4. Check the environment

```bash
./scripts/check_k_sound_hub_env.sh
```

This checks:

- required Linux commands
- PipeWire / WirePlumber services
- Python modules used by the application

### 5. Start the application

Recommended launcher:

```bash
./scripts/start_ksound_hub.sh
```

Alternative commands:

```bash
ksound-hub
```

or:

```bash
python -m ksound_hub.app
```

## Desktop launcher support

K-Sound Hub does **not** install a desktop launcher automatically.

A launcher file can be generated manually from the repository with:

```bash
./scripts/install_desktop_entry.sh
```

That generates a ready-to-use launcher file here:

```text
packaging/linux/ksound-hub.desktop
```

### Add K-Sound Hub to the application launcher menu

For desktop environments that use `~/.local/share/applications/`:

```bash
mkdir -p ~/.local/share/applications && cp "$HOME/k-sound-hub/packaging/linux/ksound-hub.desktop" ~/.local/share/applications/ && chmod +x ~/.local/share/applications/ksound-hub.desktop
```

On KDE Plasma, refresh the launcher cache with:

```bash
kbuildsycoca6
```

Then search for **K-Sound Hub** in the application launcher.

### Create a desktop shortcut

To place a launcher directly on the desktop:

```bash
cp "$HOME/k-sound-hub/packaging/linux/ksound-hub.desktop" "$HOME/Desktop/" && chmod +x "$HOME/Desktop/ksound-hub.desktop"
```

## Autostart

K-Sound Hub does **not** enable autostart automatically.

Autostart remains a manual choice.

The script intended for manual autostart is:

```bash
$HOME/k-sound-hub/scripts/start_ksound_hub.sh
```

If a `.desktop` autostart file or template is used, paths should be adjusted manually before enabling it.

The important behavior is:

- installation does **not** force autostart
- autostart remains explicit and manual

## Tray behavior

K-Sound Hub can be configured to send the application to the system tray when the window close button is pressed.

When this setting is enabled:

- clicking the window close button hides the main window
- the application continues running in the tray
- the tray menu can restore the window
- the tray menu can fully quit the application

When this setting is disabled:

- clicking the window close button exits the application normally

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
  start_ksound_hub.sh
  check_k_sound_hub_env.sh
  install_desktop_entry.sh

packaging/linux/
  ksound-hub.desktop
  ksound-hub-autostart.desktop.template
```

## Notes for installing on another Linux PC

The recommended order is:

1. clone the repository
2. create and activate `.venv`
3. install with `python -m pip install -e .`
4. run `./scripts/check_k_sound_hub_env.sh`
5. start with `./scripts/start_ksound_hub.sh`
6. optionally generate the launcher with `./scripts/install_desktop_entry.sh`
7. optionally copy the launcher into `~/.local/share/applications/`

This installation flow is intended to stay distro-agnostic. The Python installation remains the same; only the system package names for PipeWire-related tools may vary by distribution.

## License

MIT License. See `LICENSE`.

## Disclaimer

This software is provided as-is.

It should be tested carefully before being relied on for streaming, voice chat, recording, live routing, or production audio use.
