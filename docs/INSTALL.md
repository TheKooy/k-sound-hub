# Installation

K-Sounds Hub is installed from GitHub Releases.

## What to download

On the GitHub Releases page, download one of these assets:

- k-sounds-hub-linux-release-v0.3.2.tar.gz
- k-sounds-hub-linux-release-v0.3.2.zip

Do not use the green Code button for normal installation.
Do not download the automatic Source code zip or Source code tar.gz files.

## Install from tar.gz

Open a terminal in the download folder, then run:

    tar -xzf k-sounds-hub-linux-release-v0.3.2.tar.gz
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

Start the app with:

    k-sounds-hub

## Install from zip

Open a terminal in the download folder, then run:

    unzip k-sounds-hub-linux-release-v0.3.2.zip
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

Start the app with:

    k-sounds-hub

## Important notes

- Run install.sh from a terminal.
- Double-clicking install.sh in a file manager may look like nothing happened.
- install.sh installs the app but does not automatically launch it.
- If the command is not found after install, reopen the terminal or run:

    ~/.local/bin/k-sounds-hub

## If dependencies are missing

The installer checks for required commands such as pactl, parec, pw-cat and ffmpeg.

To let the installer install distro packages with sudo:

    ./install.sh --install-system-deps

For non-interactive package installation where supported:

    ./install.sh --install-system-deps --yes

## What gets installed

Default install paths:

    ~/.local/share/k-sounds-hub/app        application files
    ~/.local/share/k-sounds-hub/app/.venv  Python virtual environment
    ~/.local/bin/k-sounds-hub              user command
    ~/.local/bin/ksound-hub-v2             legacy compatibility command
    ~/.local/share/applications/k-sounds-hub.desktop
    ~/.config/k-sounds-hub                 user config, created at runtime

The installer does not:

- write to /etc
- write to /usr
- write to /opt
- enable autostart
- write global PipeWire configuration
- remove distro packages during uninstall

## Uninstall

    ~/.local/share/k-sounds-hub/app/uninstall.sh

Remove saved config too:

    ~/.local/share/k-sounds-hub/app/uninstall.sh --remove-config

## Android remote

The Android remote is a separate asset:

    KSoundsSoundboardRemote.apk

Install it manually on Android.
