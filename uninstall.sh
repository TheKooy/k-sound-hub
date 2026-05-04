#!/usr/bin/env bash
set -Eeuo pipefail

APP_ID="ksound-hub-v2"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_ROOT="$DATA_HOME/$APP_ID"
BIN_PATH="$HOME/.local/bin/ksound-hub-v2"
DESKTOP_ENTRY_PATH="$DATA_HOME/applications/ksound-hub-v2.desktop"
DESKTOP_SHORTCUT_PATH="$HOME/Desktop/ksound-hub-v2.desktop"
REMOVE_CONFIG=0

usage() {
  cat <<'USAGE'
K-Sound Hub V2 user uninstall

Usage:
  ./uninstall.sh [--remove-config]

This removes only user-installed K-Sound Hub files.
It does not remove distro packages.
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --remove-config) REMOVE_CONFIG=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 2 ;;
  esac
done

rm -f "$BIN_PATH" "$DESKTOP_ENTRY_PATH" "$DESKTOP_SHORTCUT_PATH"
rm -rf "$APP_ROOT"

if (( REMOVE_CONFIG )); then
  rm -rf "$CONFIG_HOME/ksound-hub-v2"
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true

cat <<EOF_DONE
K-Sound Hub V2 user install removed.

Removed:
  $APP_ROOT
  $BIN_PATH
  $DESKTOP_ENTRY_PATH

Config removed: $([[ "$REMOVE_CONFIG" == 1 ]] && echo yes || echo no)
EOF_DONE
