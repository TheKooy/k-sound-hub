#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(python - <<'PY'
from pathlib import Path
import re
text = Path('pyproject.toml').read_text(encoding='utf-8')
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
if not match:
    raise SystemExit('Could not read version from pyproject.toml')
print(match.group(1))
PY
)"
fi

TAG="v$VERSION"
DIST_DIR="$REPO_DIR/dist"
BUILD_ROOT="$REPO_DIR/build/release"
PACKAGE_DIR="$BUILD_ROOT/ksound-hub-v2-linux-release-$TAG"
TAR_PATH="$DIST_DIR/ksound-hub-v2-linux-release-$TAG.tar.gz"
ZIP_PATH="$DIST_DIR/ksound-hub-v2-linux-release-$TAG.zip"
SUMS_PATH="$DIST_DIR/SHA256SUMS.txt"

rm -rf "$BUILD_ROOT"
mkdir -p "$PACKAGE_DIR" "$DIST_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='build/' \
    --exclude='dist/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.jks' \
    --exclude='*.keystore' \
    --exclude='*.apk' \
    --exclude='*.tar.gz' \
    --exclude='*.zip' \
    "$REPO_DIR/" "$PACKAGE_DIR/"
else
  git archive --format=tar HEAD | tar -xf - -C "$PACKAGE_DIR"
fi

if [[ -n "${KSH_APK_PATH:-}" ]]; then
  if [[ ! -f "$KSH_APK_PATH" ]]; then
    echo "KSH_APK_PATH does not exist: $KSH_APK_PATH" >&2
    exit 1
  fi
  mkdir -p "$PACKAGE_DIR/optional/android"
  cp -a "$KSH_APK_PATH" "$PACKAGE_DIR/optional/android/KSoundSoundboard.apk"
fi

chmod +x "$PACKAGE_DIR/install.sh" "$PACKAGE_DIR/uninstall.sh" "$PACKAGE_DIR/scripts/"*.sh

bash -n "$PACKAGE_DIR/install.sh"
bash -n "$PACKAGE_DIR/uninstall.sh"
for f in "$PACKAGE_DIR/scripts/"*.sh; do bash -n "$f"; done

rm -f "$TAR_PATH" "$ZIP_PATH" "$SUMS_PATH"
(
  cd "$BUILD_ROOT"
  tar -czf "$TAR_PATH" "$(basename "$PACKAGE_DIR")"
)
(
  cd "$BUILD_ROOT"
  zip -qr "$ZIP_PATH" "$(basename "$PACKAGE_DIR")"
)
(
  cd "$DIST_DIR"
  sha256sum "$(basename "$TAR_PATH")" "$(basename "$ZIP_PATH")" > "$SUMS_PATH"
)

cat <<EOF_DONE
Release files created:
  $TAR_PATH
  $ZIP_PATH
  $SUMS_PATH

Optional APK included: $([[ -n "${KSH_APK_PATH:-}" ]] && echo yes || echo no)
EOF_DONE
