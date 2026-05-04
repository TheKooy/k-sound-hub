# K-Sounds Hub v0.3.4

Responsiveness and monitoring polish release.

## Fixes

- Improved live volume responsiveness for playback channels.
- Improved MIC OUT / microphone monitoring responsiveness.
- Reduced crack/pop behavior when changing monitored microphone sources.
- Hid internal keepalive and K-Sounds internal streams from app selection.
- Centered selected device labels while keeping hover scrolling for long names.

## Downloads

Download the release assets, not the automatic Source code files.

- Linux desktop app: k-sounds-hub-linux-release-v0.3.4.tar.gz
- Linux desktop app zip: k-sounds-hub-linux-release-v0.3.4.zip
- Android soundboard remote: KSoundsSoundboardRemote.apk
- Checksums: SHA256SUMS.txt

## Linux install / update

Open a terminal in your download folder.

For the tar.gz release:

    tar -xzf k-sounds-hub-linux-release-v0.3.4.tar.gz
    cd k-sounds-hub-linux-release-v0.3.4
    ./install.sh

For the zip release:

    unzip k-sounds-hub-linux-release-v0.3.4.zip
    cd k-sounds-hub-linux-release-v0.3.4
    ./install.sh

Start the app with:

    k-sounds-hub

## Notes

- Run install.sh from a terminal.
- install.sh installs or updates the app but does not automatically launch it.
- Device choices are detected on each machine and saved in ~/.config/k-sounds-hub/settings.json.
