#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_DIR/packaging/linux"
OUT_FILE="$OUT_DIR/ksound-hub.desktop"
EXEC_PATH="$REPO_DIR/scripts/start_ksound_hub.sh"
ICON_PATH="$REPO_DIR/src/ksound_hub/assets/app_icon.png"

mkdir -p "$OUT_DIR"

cat > "$OUT_FILE" <<EOF2
[Desktop Entry]
Type=Application
Version=1.0
Name=K-Sound Hub
Comment=PipeWire-first modular Linux audio hub
Exec=$EXEC_PATH
Icon=$ICON_PATH
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
X-GNOME-UsesNotifications=true
EOF2

chmod +x "$OUT_FILE"

echo "Launcher created:"
echo "  $OUT_FILE"
echo
echo "You can copy this file wherever you want:"
echo "  - Desktop"
echo "  - ~/.local/share/applications/"
echo "  - panel/dock launchers depending on your desktop"
echo
echo "Nothing was added to autostart."
