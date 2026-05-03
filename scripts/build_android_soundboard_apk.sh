#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO/android-soundboard-apk"
DIST_DIR="$REPO/dist"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
BUILD_TOOLS="$SDK/build-tools/37.0.0"
ANDROID_JAR="$SDK/platforms/android-37.0/android.jar"

AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

KEYSTORE="$APP_DIR/ksound-soundboard.keystore"
SIGNED_APK="$DIST_DIR/KSoundSoundboard.apk"
UNSIGNED_APK="$APP_DIR/unsigned.unaligned.apk"
ALIGNED_APK="$APP_DIR/aligned.apk"

GEN_DIR="$APP_DIR/gen"
CLASSES_DIR="$APP_DIR/classes"
DEX_DIR="$APP_DIR/dex"

for f in "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR" "$KEYSTORE"; do
  [[ -e "$f" ]] || { echo "Missing: $f" >&2; exit 1; }
done

detect_keystore_password() {
  if [[ -n "${KSOUND_SOUNDBOARD_KEYSTORE_PASS:-}" ]]; then
    printf '%s' "$KSOUND_SOUNDBOARD_KEYSTORE_PASS"
    return 0
  fi

  local candidates=(
    "ksound"
    "ksoundhub"
    "ksoundhubv2"
    "ksound-soundboard"
    "ksoundsoundboard"
    "KSoundSoundboard"
    "android"
    "changeit"
    "kooy"
    "Kooy"
    "123456"
  )

  local pass
  for pass in "${candidates[@]}"; do
    if keytool -list -keystore "$KEYSTORE" -storepass "$pass" >/dev/null 2>&1; then
      printf '%s' "$pass"
      return 0
    fi
  done

  return 1
}

KS_PASS="$(detect_keystore_password || true)"
if [[ -z "$KS_PASS" ]]; then
  echo "Could not auto-detect keystore password." >&2
  exit 1
fi

KEY_PASS="${KSOUND_SOUNDBOARD_KEY_PASS:-$KS_PASS}"
KEY_ALIAS="${KSOUND_SOUNDBOARD_KEY_ALIAS:-}"

if [[ -z "$KEY_ALIAS" ]]; then
  KEY_ALIAS="$(
    LANG=C keytool -list -keystore "$KEYSTORE" -storepass "$KS_PASS" 2>/dev/null \
      | awk -F, '/PrivateKeyEntry/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1); print $1; exit}'
  )"
fi

if [[ -z "$KEY_ALIAS" ]]; then
  echo "Could not detect key alias." >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
rm -rf "$GEN_DIR" "$CLASSES_DIR" "$DEX_DIR"
rm -f "$SIGNED_APK" "$SIGNED_APK.idsig" "$UNSIGNED_APK" "$ALIGNED_APK"
mkdir -p "$GEN_DIR" "$CLASSES_DIR" "$DEX_DIR"

echo "===== AAPT GENERATE R.java ====="
"$AAPT" package \
  -f \
  -m \
  -J "$GEN_DIR" \
  -M "$APP_DIR/AndroidManifest.xml" \
  -S "$APP_DIR/res" \
  -I "$ANDROID_JAR"

echo
echo "===== JAVAC ====="
mapfile -t JAVA_FILES < <(find "$APP_DIR/src" "$GEN_DIR" -type f -name '*.java' | sort)

javac \
  -encoding UTF-8 \
  -source 8 \
  -target 8 \
  -bootclasspath "$ANDROID_JAR" \
  -classpath "$ANDROID_JAR" \
  -d "$CLASSES_DIR" \
  "${JAVA_FILES[@]}"

echo
echo "===== D8 ====="
"$D8" \
  --min-api 23 \
  --lib "$ANDROID_JAR" \
  --output "$DEX_DIR" \
  $(find "$CLASSES_DIR" -type f -name '*.class' | sort)

echo
echo "===== PACKAGE APK ====="
"$AAPT" package \
  -f \
  -M "$APP_DIR/AndroidManifest.xml" \
  -S "$APP_DIR/res" \
  -I "$ANDROID_JAR" \
  -F "$UNSIGNED_APK"

(
  cd "$DEX_DIR"
  zip -q -u "$UNSIGNED_APK" classes.dex
)

echo
echo "===== ZIPALIGN ====="
"$ZIPALIGN" -f 4 "$UNSIGNED_APK" "$ALIGNED_APK"

echo
echo "===== SIGN V1+V2+V3 ====="
echo "Using key alias: $KEY_ALIAS"

"$APKSIGNER" sign \
  --ks "$KEYSTORE" \
  --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "pass:$KS_PASS" \
  --key-pass "pass:$KEY_PASS" \
  --v1-signing-enabled true \
  --v2-signing-enabled true \
  --v3-signing-enabled true \
  --out "$SIGNED_APK" \
  "$ALIGNED_APK"

echo
echo "===== VERIFY APK ====="
"$APKSIGNER" verify --verbose --print-certs "$SIGNED_APK"

echo
echo "===== BADGING ====="
"$AAPT" dump badging "$SIGNED_APK" | sed -n '1,60p'

echo
echo "===== DONE ====="
ls -lh "$SIGNED_APK"
