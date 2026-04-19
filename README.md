# K-Sound Hub

K-Sound Hub is the successor to the original **Carla Hub** experiment.

The first project started as a personal Linux audio control panel built around Carla, qpwgraph, PipeWire and custom scripts. This rewrite moves the project toward a cleaner, installable and reusable open-source application with a stronger focus on:

- PipeWire-first routing
- a self-contained control UI
- modular channels
- persistent settings
- optional overlay and visual widgets
- per-channel EQ profiles
- deployability on another PC without the old ad-hoc project layout

> This project is being developed with AI assistance.

## Current status

This repository is the **bootstrap for the rewrite**.

It already includes:

- a proper Python package layout
- an installable desktop application entry point
- persistent settings storage
- modular channels that can be added, removed, enabled and disabled
- optional overlay / visualizer settings
- per-channel EQ profile data management
- a simple channel UI with a lightweight VU-style visualizer widget
- a PipeWire backend abstraction layer prepared for the next implementation phases
- a project structure ready for Git, GitHub and CI

What it does **not** implement yet:

- the full production PipeWire routing engine that replaces the old Carla-based chain
- the final no-Carla EQ processing backend
- the optional external overlay process
- app routing and microphone routing parity with the current Carla Hub 4.2.0 setup

The goal is to build that in clean phases instead of copying the current ad-hoc stack directly.

## Design goals

- no dependency on Carla for the new engine
- qpwgraph only for visualization and debugging
- persistent, deterministic backend state
- modular channels controlled by the UI
- easy deployment on another Linux PC
- source-controlled project with documented installation steps

## Planned phases

### Phase 0
Repository bootstrap, package layout, settings model, installable GUI shell.

### Phase 1
PipeWire device/channel discovery and persistence.

### Phase 2
Channel routing engine without Carla.

### Phase 3
Per-channel EQ backend without Carla.

### Phase 4
Microphone / return-monitoring / app-send parity with the old project.

### Phase 5
Optional overlay and additional polish.

## Requirements

Target platform for the first iterations:

- Linux
- PipeWire / WirePlumber
- KDE Plasma / Wayland is the expected first target
- Python 3.11+

## Python dependencies

Main runtime dependency:

- `PySide6`

Optional development tools:

- `pytest`
- `ruff`

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

### 3. Install the app in editable mode

```bash
pip install -e .
```

### 4. Run it

```bash
ksound-hub
```

## Development run

```bash
python -m ksound_hub.app
```

## Tests

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
  audio/
    engine.py
    pipewire.py
  ui/
    main_window.py
    channel_widget.py
    settings_dialog.py
    widgets.py
```

## GitHub first push

After you create the empty GitHub repository:

```bash
git init
git branch -M main
git add .
git commit -m "Initial K-Sound Hub bootstrap"
git remote add origin <YOUR-REPO-URL>
git push -u origin main
```

## Roadmap notes

The current working local project remains **Carla Hub 4.2.0** until K-Sound Hub becomes functionally ready.

K-Sound Hub is intended to replace that project gradually, not by breaking the working setup first.

## Disclaimer

This software is provided as-is. You are responsible for testing it on your own system before trusting it in production, streaming, voice chat, recording or live routing scenarios.

See also `DISCLAIMER.md` and `LICENSE`.

## License

MIT License. See `LICENSE`.
