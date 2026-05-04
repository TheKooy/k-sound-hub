#!/usr/bin/env bash
set -Eeuo pipefail

APP_ID="ksound-hub-v2"
APP_NAME="K-Sound Hub V2"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_ROOT="$DATA_HOME/$APP_ID"
APP_DIR="$APP_ROOT/app"
VENV_DIR="$APP_DIR/.venv"
BIN_DIR="$HOME/.local/bin"
WRAPPER_PATH="$BIN_DIR/ksound-hub-v2"
APPS_DIR="$DATA_HOME/applications"
DESKTOP_ENTRY_PATH="$APPS_DIR/ksound-hub-v2.desktop"
DESKTOP_SHORTCUT_PATH="$HOME/Desktop/ksound-hub-v2.desktop"

ASSUME_YES=0
INSTALL_SYSTEM_DEPS=0
INSTALL_DESKTOP=1
MAKE_DESKTOP_SHORTCUT=0
BUILD_NATIVE=0
RUN_CHECK=1

usage() {
  cat <<'USAGE'
K-Sound Hub V2 non-invasive user installer

Usage:
  ./install.sh [options]

Default behavior:
  - installs only into the current user's home directory
  - copies the app to ~/.local/share/ksound-hub-v2/app
  - creates ~/.local/share/ksound-hub-v2/app/.venv
  - creates ~/.local/bin/ksound-hub-v2
  - creates ~/.local/share/applications/ksound-hub-v2.desktop
  - does not enable autostart
  - does not write /etc, /usr, /opt, or global PipeWire config

Options:
      --install-system-deps  Install distro packages with sudo when dependencies are missing.
  -y, --yes                  Use non-interactive package manager mode where supported.
      --no-desktop           Do not install the app-menu launcher.
      --desktop-shortcut     Also create a desktop shortcut.
      --build-native         Build the optional native engine after install.
      --no-check             Skip the final environment check.
  -h, --help                 Show this help.

Examples:
  ./install.sh
  ./install.sh --install-system-deps
  ./install.sh --install-system-deps --yes
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --install-system-deps) INSTALL_SYSTEM_DEPS=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    --no-desktop) INSTALL_DESKTOP=0 ;;
    --desktop-shortcut) MAKE_DESKTOP_SHORTCUT=1 ;;
    --build-native) BUILD_NATIVE=1 ;;
    --no-check) RUN_CHECK=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 2 ;;
  esac
done

log() { printf '\n===== %s =====\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
need_cmd() { command -v "$1" >/dev/null 2>&1; }

run_root() {
  if (( EUID == 0 )); then
    "$@"
  elif need_cmd sudo; then
    sudo "$@"
  else
    echo "sudo is required for this optional system dependency step: $*" >&2
    exit 1
  fi
}

read_os_release() {
  OS_ID="unknown"
  OS_LIKE=""
  OS_NAME="unknown Linux"
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
    OS_NAME="${PRETTY_NAME:-${NAME:-unknown Linux}}"
  fi
}

pkg_args_yes() {
  local pm="$1"
  case "$pm" in
    pacman) (( ASSUME_YES )) && printf '%s\n' --noconfirm ;;
    apt) (( ASSUME_YES )) && printf '%s\n' -y ;;
    dnf) (( ASSUME_YES )) && printf '%s\n' -y ;;
    zypper) (( ASSUME_YES )) && printf '%s\n' --non-interactive ;;
  esac
}

install_system_deps() {
  read_os_release
  log "Installing system dependencies"
  echo "Detected: $OS_NAME"
  local id_like=" $OS_ID $OS_LIKE "

  if [[ "$id_like" == *" arch "* ]] || [[ "$id_like" == *" manjaro "* ]] || [[ "$OS_ID" == "endeavouros" ]]; then
    local yes_args=()
    mapfile -t yes_args < <(pkg_args_yes pacman)
    run_root pacman -S --needed "${yes_args[@]}" \
      python python-pip python-virtualenv \
      pipewire pipewire-pulse wireplumber libpulse \
      ffmpeg xdg-utils desktop-file-utils xcb-util-cursor
    return 0
  fi

  if [[ "$id_like" == *" debian "* ]] || [[ "$id_like" == *" ubuntu "* ]] || need_cmd apt-get; then
    local yes_args=()
    mapfile -t yes_args < <(pkg_args_yes apt)
    run_root apt-get update
    run_root apt-get install "${yes_args[@]}" \
      python3 python3-venv python3-pip \
      pipewire pipewire-pulse wireplumber pipewire-bin pulseaudio-utils \
      ffmpeg libxcb-cursor0 xdg-utils desktop-file-utils
    return 0
  fi

  if [[ "$id_like" == *" fedora "* ]] || [[ "$id_like" == *" rhel "* ]] || [[ "$id_like" == *" centos "* ]] || need_cmd dnf; then
    local yes_args=()
    mapfile -t yes_args < <(pkg_args_yes dnf)
    run_root dnf install "${yes_args[@]}" \
      python3 python3-pip python3-virtualenv \
      pipewire pipewire-pulseaudio wireplumber pulseaudio-utils \
      ffmpeg-free xdg-utils desktop-file-utils xcb-util-cursor
    return 0
  fi

  if [[ "$id_like" == *" suse "* ]] || need_cmd zypper; then
    local yes_args=()
    mapfile -t yes_args < <(pkg_args_yes zypper)
    run_root zypper "${yes_args[@]}" install --no-recommends \
      python3 python3-pip python3-virtualenv \
      pipewire pipewire-pulseaudio wireplumber pulseaudio-utils \
      ffmpeg xdg-utils desktop-file-utils libxcb-cursor0
    return 0
  fi

  cat >&2 <<'MSG'
Unsupported or unknown distribution for automatic dependency installation.
Install these manually, then rerun ./install.sh:
  python3.11+, python venv, pip, PipeWire, WirePlumber, PipeWire Pulse compatibility,
  pactl/parec client tools, pw-cat, ffmpeg, xdg-utils, desktop-file-utils.
MSG
  exit 1
}

find_python() {
  local candidates=(python3.13 python3.12 python3.11 python3 python)
  local c
  for c in "${candidates[@]}"; do
    need_cmd "$c" || continue
    if "$c" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

missing_runtime_commands() {
  local missing=()
  local cmd
  for cmd in pactl parec pw-cat ffmpeg; do
    need_cmd "$cmd" || missing+=("$cmd")
  done
  if ((${#missing[@]})); then
    printf '%s\n' "${missing[@]}"
  fi
}

print_dependency_help() {
  read_os_release
  cat <<EOF_HELP
Missing required runtime commands:
$(missing_runtime_commands | sed 's/^/  - /')

K-Sound Hub was not installed yet.

Recommended non-invasive flow:
  1. Install distro packages yourself, or rerun with:
       ./install.sh --install-system-deps

Detected distro:
  $OS_NAME
EOF_HELP
}

copy_app() {
  log "Copying app into user data directory"
  mkdir -p "$APP_ROOT"
  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"

  if need_cmd rsync; then
    rsync -a --delete \
      --exclude='.git/' \
      --exclude='.venv/' \
      --exclude='venv/' \
      --exclude='__pycache__/' \
      --exclude='.pytest_cache/' \
      --exclude='.ruff_cache/' \
      --exclude='.mypy_cache/' \
      --exclude='build/' \
      --exclude='dist/' \
      --exclude='*.pyc' \
      "$SOURCE_DIR/" "$APP_DIR/"
  else
    (cd "$SOURCE_DIR" && tar \
      --exclude='./.git' \
      --exclude='./.venv' \
      --exclude='./venv' \
      --exclude='./__pycache__' \
      --exclude='./.pytest_cache' \
      --exclude='./.ruff_cache' \
      --exclude='./.mypy_cache' \
      --exclude='./build' \
      --exclude='./dist' \
      -cf - .) | (cd "$APP_DIR" && tar -xf -)
  fi
}

setup_python_env() {
  log "Creating Python virtual environment"
  local py
  py="$(find_python)" || {
    echo "Python 3.11+ was not found." >&2
    exit 1
  }
  echo "Using Python: $($py -c 'import sys; print(sys.executable, sys.version.split()[0])')"

  "$py" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
  "$VENV_DIR/bin/python" -m pip install -e "$APP_DIR"
}

install_wrapper() {
  log "Installing user command"
  mkdir -p "$BIN_DIR"
  cat > "$WRAPPER_PATH" <<EOF_WRAPPER
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$APP_DIR/scripts/start_ksound_hub_v2.sh" "\$@"
EOF_WRAPPER
  chmod +x "$WRAPPER_PATH"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in PATH. Add it to PATH or launch with: $WRAPPER_PATH" ;;
  esac
}

install_desktop_launcher() {
  (( INSTALL_DESKTOP )) || return 0
  log "Installing app-menu launcher"
  mkdir -p "$APPS_DIR"
  local icon_path="$APP_DIR/src/ksound_hub/assets/app_icon.png"
  cat > "$DESKTOP_ENTRY_PATH" <<EOF_DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=PipeWire-first modular Linux audio hub
Exec=$WRAPPER_PATH
Icon=$icon_path
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
X-GNOME-UsesNotifications=true
EOF_DESKTOP
  chmod +x "$DESKTOP_ENTRY_PATH"

  if (( MAKE_DESKTOP_SHORTCUT )); then
    mkdir -p "$HOME/Desktop"
    cp "$DESKTOP_ENTRY_PATH" "$DESKTOP_SHORTCUT_PATH"
    chmod +x "$DESKTOP_SHORTCUT_PATH"
  fi

  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true
}

build_native_engine() {
  (( BUILD_NATIVE )) || return 0
  log "Building optional native engine"
  "$APP_DIR/scripts/build_ksound_native_engine.sh" "$APP_DIR"
}

run_final_check() {
  (( RUN_CHECK )) || return 0
  log "Final environment check"
  "$APP_DIR/scripts/check_k_sound_hub_env.sh" || warn "Environment check reported issues. The install files were still created."
}

main() {
  if (( EUID == 0 )); then
    echo "Do not run this installer as root. It is a user install." >&2
    echo "Use ./install.sh --install-system-deps if you want the script to call sudo only for packages." >&2
    exit 1
  fi

  if [[ ! -f "$SOURCE_DIR/pyproject.toml" || ! -d "$SOURCE_DIR/src/ksound_hub" ]]; then
    echo "This installer must be run from the extracted K-Sound Hub source/release directory." >&2
    exit 1
  fi

  if (( INSTALL_SYSTEM_DEPS )); then
    install_system_deps
  else
    local missing_file="/tmp/ksound-hub-missing.$$"
    missing_runtime_commands >"$missing_file"
    if [[ -s "$missing_file" ]]; then
      rm -f "$missing_file"
      print_dependency_help
      exit 2
    fi
    rm -f "$missing_file"
  fi

  copy_app
  setup_python_env
  install_wrapper
  install_desktop_launcher
  build_native_engine
  run_final_check

  log "Install complete"
  cat <<EOF_DONE
Installed app:
  $APP_DIR

User command:
  $WRAPPER_PATH

App menu launcher:
  $DESKTOP_ENTRY_PATH

User config will live in:
  $CONFIG_HOME/ksound-hub-v2

Start with:
  ksound-hub-v2

No autostart was enabled. No global PipeWire config was written.
EOF_DONE
}

main "$@"
