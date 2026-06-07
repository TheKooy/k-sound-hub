#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

already_running() {
  "$PY" - <<'PY'
from pathlib import Path
import os
import sys

self_pid = os.getpid()
parent_pid = os.getppid()
patterns = (
    "-m ksound_hub.glass_app",
    "ksound_hub.glass_app",
    "src/ksound_hub/glass_app.py",
)

for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        pid = int(entry.name)
    except Exception:
        continue
    if pid in {self_pid, parent_pid}:
        continue
    try:
        raw = (entry / "cmdline").read_bytes()
    except Exception:
        continue
    if not raw:
        continue

    cmd = " ".join(part.decode("utf-8", "ignore") for part in raw.split(b"\0") if part)
    if any(pattern in cmd for pattern in patterns):
        print(f"K-Sounds Hub Glass is already running: PID {pid}", file=sys.stderr)
        sys.exit(0)

sys.exit(1)
PY
}

if already_running; then
  exit 0
fi

LOCK_DIR="${XDG_RUNTIME_DIR:-/tmp}"
LOCK_FILE="$LOCK_DIR/ksounds-hub-glass-${UID:-$(id -u)}.lock"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "K-Sounds Hub Glass is already starting/running." >&2
  exit 0
fi

# Re-check after the lock to avoid double-click races.
if already_running; then
  exit 0
fi

export KSH_CONFIG_DIR="${KSH_CONFIG_DIR:-$HOME/.config/k-sounds-hub}"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

cd "$REPO"
exec "$PY" -m ksound_hub.glass_app "$@"
