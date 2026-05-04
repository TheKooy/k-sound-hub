# Installation

K-Sounds Hub uses a non-invasive user install by default.

## What gets installed

Default install paths:

```text
~/.local/share/k-sounds-hub/app        application files
~/.local/share/k-sounds-hub/app/.venv  Python virtual environment
~/.local/bin/k-sounds-hub              user command
~/.local/share/applications/k-sounds-hub.desktop
~/.config/k-sounds-hub                 user config, created at runtime
```

The installer does **not**:

- write to `/etc`
- write to `/usr`
- write to `/opt`
- enable autostart
- write global PipeWire configuration
- remove distro packages during uninstall

## Install from an extracted release

```bash
./install.sh
```

When dependencies are missing, the installer stops and tells you what is missing.
To let the installer install distro packages with `sudo`:

```bash
./install.sh --install-system-deps
```

For non-interactive distro package installs where supported:

```bash
./install.sh --install-system-deps --yes
```

## Start

```bash
k-sounds-hub
```

## Uninstall

```bash
~/.local/share/k-sounds-hub/app/uninstall.sh
```

Remove saved config too:

```bash
~/.local/share/k-sounds-hub/app/uninstall.sh --remove-config
```

## Runtime dependencies

Required commands:

- `python3` 3.11 or newer
- `pactl`
- `parec`
- `pw-cat`
- `ffmpeg`

Expected audio stack:

- PipeWire
- PipeWire PulseAudio compatibility
- WirePlumber

Python dependencies are installed into the app-local virtual environment:

- PySide6
- NumPy
