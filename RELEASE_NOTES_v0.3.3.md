# K-Sounds Hub v0.3.3

Device portability fix release.

## Important fix

K-Sounds Hub no longer contains hard-coded personal audio device names.

Playback outputs and microphone inputs are now detected at runtime from PipeWire/PulseAudio using `pactl`.

## Downloads

Download the release assets, not the automatic Source code files.

- Linux desktop app: k-sounds-hub-linux-release-v0.3.3.tar.gz
- Linux desktop app zip: k-sounds-hub-linux-release-v0.3.3.zip
- Android soundboard remote: KSoundsSoundboardRemote.apk
- Checksums: SHA256SUMS.txt

## Linux install

Open a terminal in your download folder.

For the tar.gz release:

    tar -xzf k-sounds-hub-linux-release-v0.3.3.tar.gz
    cd k-sounds-hub-linux-release-v0.3.3
    ./install.sh

For the zip release:

    unzip k-sounds-hub-linux-release-v0.3.3.zip
    cd k-sounds-hub-linux-release-v0.3.3
    ./install.sh

Start the app with:

    k-sounds-hub

## Notes

- Run install.sh from a terminal.
- install.sh installs the app but does not automatically launch it.
- If no device is selected, the app uses the current PipeWire default output/source.
- Device choices are detected on each machine and saved in `~/.config/k-sounds-hub/settings.json`.

