# K-Sound Hub

K-Sound Hub is a PipeWire-first modular Linux audio hub focused on a clean UI, persistent settings, per-channel control, app routing, EQ profiles, overlay feedback, and optional wallpaper background support.

> This project is being developed with AI assistance.

## Target platform

Primary target:

- EndeavourOS / Arch Linux
- PipeWire + WirePlumber
- KDE Plasma / Wayland
- Python 3.11+

## Runtime dependencies

### System packages

Install or update the required Arch packages:

```bash
sudo pacman -Syu --needed git python python-pip python-virtualenv pipewire pipewire-pulse wireplumber
```

These cover the expected runtime base for K-Sound Hub on Arch-family systems:

- `git`
- `python`
- `python-pip`
- `python-virtualenv`
- `pipewire`
- `pipewire-pulse`
- `wireplumber`

### Python packages

The project installs its Python-side dependencies from `pyproject.toml`:

- `PySide6`
- `numpy`

Optional development tools:

- `pytest`
- `ruff`

## Quick install on another PC

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

If you also want the dev tools:

```bash
python -m pip install -e .[dev]
```

## Verify the environment

A helper script is included:

```bash
./scripts/check_k_sound_hub_env.sh
```

It checks the main commands and Python modules expected by the current project.

## Run the application

Preferred launcher from the repository root:

```bash
./scripts/start_ksound_hub.sh
```

You can also run it directly after install:

```bash
ksound-hub
```

Or from source:

```bash
PYTHONPATH=src python -m ksound_hub.app
```

## Optional autostart

Autostart is **not enabled automatically**.

A template file is included here:

```text
packaging/linux/ksound-hub-autostart.desktop.template
```

To use it manually:

1. Open the template.
2. Replace `__REPO_DIR__` with the absolute path to your local repository.
3. Save it as:

```text
~/.config/autostart/ksound-hub.desktop
```

Example:

```bash
mkdir -p ~/.config/autostart
sed "s|__REPO_DIR__|$HOME/k-sound-hub|g" \
  packaging/linux/ksound-hub-autostart.desktop.template \
  > ~/.config/autostart/ksound-hub.desktop
```

That is only a manual setup step. Nothing in the project enables autostart by itself.

## Included helper scripts

### Start script

```text
scripts/start_ksound_hub.sh
```

This script:

- resolves the repository root automatically
- prefers the local virtualenv if present
- starts the installed app or falls back to module execution from source

### Environment check script

```text
scripts/check_k_sound_hub_env.sh
```

This script prints the state of:

- PipeWire-related commands
- Python
- virtualenv
- required Python modules

## Development

Run tests:

```bash
pytest
```

## Repository layout

```text
src/ksound_hub/
  app.py
  config.py
  models.py
  settings_store.py
  control.py
  ipc.py
  audio/
    engine.py
    pipewire.py
  ui/
    main_window.py
    channel_widget.py
    settings_dialog.py
    overlay.py
    widgets.py
scripts/
  start_ksound_hub.sh
  check_k_sound_hub_env.sh
packaging/linux/
  ksound-hub-autostart.desktop.template
```

## Notes

- This project does **not** auto-register itself in autostart during installation.
- The provided autostart file is only a ready-to-use manual template.
- The local virtualenv approach is the recommended install method for now.

## Disclaimer

This software is provided as-is. You are responsible for testing it on your own system before trusting it for production, streaming, voice chat, recording or live routing.

See also `DISCLAIMER.md` and `LICENSE`.

## License

MIT License. See `LICENSE`.
