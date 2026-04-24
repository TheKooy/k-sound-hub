#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${1:-$HOME/k-sound-hub-v2}"
SRC_DIR="$REPO/native_engine"
BUILD_DIR="$SRC_DIR/build"

[[ -d "$SRC_DIR" ]] || { echo "Native engine source introuvable: $SRC_DIR" >&2; exit 1; }
command -v cmake >/dev/null 2>&1 || { echo "cmake introuvable" >&2; exit 1; }
command -v c++ >/dev/null 2>&1 || command -v g++ >/dev/null 2>&1 || { echo "compilateur C++ introuvable" >&2; exit 1; }

cmake -S "$SRC_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" -j"$(nproc)"

echo
ls -l "$BUILD_DIR/ksound_native_engine"
