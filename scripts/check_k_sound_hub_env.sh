#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "===== REPO ====="
pwd
echo

echo "===== CORE COMMANDS ====="
for cmd in python pip pactl parec pw-cat ffmpeg; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '%-10s %s\n' "$cmd" "$(command -v "$cmd")"
  else
    printf '%-10s %s\n' "$cmd" "missing"
  fi
done
echo

echo "===== PIPEWIRE SERVICES ====="
systemctl --user --no-pager --full --lines=0 status pipewire.service pipewire-pulse.service wireplumber.service 2>/dev/null \
  | sed -n '/Loaded:/p;/Active:/p' || true
echo

echo "===== PYTHON MODULES ====="
PYTHON_BIN="python"
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
fi

"$PYTHON_BIN" - <<'PY'
mods = ["PySide6", "numpy"]
for mod in mods:
    try:
        __import__(mod)
        print(f"{mod}: OK")
    except Exception as exc:
        print(f"{mod}: MISSING ({exc.__class__.__name__}: {exc})")
PY
