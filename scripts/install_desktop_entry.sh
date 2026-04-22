#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGING_DIR="$REPO_DIR/packaging/linux"
TEMPLATE_PATH="$PACKAGING_DIR/ksound-hub.desktop.template"
USER_APPS_DIR="$HOME/.local/share/applications"
USER_DESKTOP_PATH="$USER_APPS_DIR/ksound-hub.desktop"
DESKTOP_SHORTCUT_PATH="$HOME/Desktop/ksound-hub.desktop"
EXEC_PATH="$REPO_DIR/scripts/start_ksound_hub.sh"
ICON_PATH="$REPO_DIR/src/ksound_hub/assets/app_icon.png"

QUIET=0
MAKE_DESKTOP_SHORTCUT=0

for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --desktop-shortcut) MAKE_DESKTOP_SHORTCUT=1 ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$PACKAGING_DIR" "$USER_APPS_DIR"

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  cat > "$TEMPLATE_PATH" <<'TPL'
[Desktop Entry]
Type=Application
Version=1.0
Name=K-Sound Hub
Comment=PipeWire-first modular Linux audio hub
Exec=__EXEC__
Icon=__ICON__
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
X-GNOME-UsesNotifications=true
TPL
fi

python - "$TEMPLATE_PATH" "$USER_DESKTOP_PATH" "$EXEC_PATH" "$ICON_PATH" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
user_desktop_path = Path(sys.argv[2])
exec_path = sys.argv[3]
icon_path = sys.argv[4]

template = template_path.read_text(encoding="utf-8")
content = template.replace("__EXEC__", exec_path).replace("__ICON__", icon_path)

user_desktop_path.write_text(content, encoding="utf-8")
PY

chmod +x "$USER_DESKTOP_PATH"

if (( MAKE_DESKTOP_SHORTCUT )); then
  mkdir -p "$HOME/Desktop"
  cp "$USER_DESKTOP_PATH" "$DESKTOP_SHORTCUT_PATH"
  chmod +x "$DESKTOP_SHORTCUT_PATH"
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 >/dev/null 2>&1 || true
fi

if (( QUIET == 0 )); then
  echo "Launcher installed for app menu:"
  echo "  $USER_DESKTOP_PATH"
  echo
  if (( MAKE_DESKTOP_SHORTCUT )); then
    echo "Desktop shortcut installed:"
    echo "  $DESKTOP_SHORTCUT_PATH"
    echo
  fi
  echo "Nothing was added to autostart."
fi
