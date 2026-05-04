# K-Sounds Hub v0.3.2

Branding cleanup release and current public release.

## Downloads

Download the release assets, not the automatic Source code files.

- Linux desktop app: k-sounds-hub-linux-release-v0.3.2.tar.gz
- Linux desktop app zip: k-sounds-hub-linux-release-v0.3.2.zip
- Android soundboard remote: KSoundsSoundboardRemote.apk
- Checksums: SHA256SUMS.txt

## Linux install

Open a terminal in your download folder.

For the tar.gz release:

    tar -xzf k-sounds-hub-linux-release-v0.3.2.tar.gz
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

For the zip release:

    unzip k-sounds-hub-linux-release-v0.3.2.zip
    cd k-sounds-hub-linux-release-v0.3.2
    ./install.sh

Start the app with:

    k-sounds-hub

Legacy command kept for compatibility:

    ksound-hub-v2

If system dependencies are missing and you want the installer to install them with sudo:

    ./install.sh --install-system-deps

## Notes

- Run install.sh from a terminal.
- install.sh installs the app but does not automatically launch it.
- The desktop app is titled K-Sounds Hub.
- The version is visible in Settings, not in the main window title.
- The Android APK is titled K-Sounds Soundboard Remote.
- The Linux installer is non-invasive by default.
- It installs into the user's home directory.
- It does not enable autostart.
- It does not write global PipeWire configuration.
