#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO/android-soundboard-apk"
DIST_DIR="$REPO/dist"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
BUILD_TOOLS="${ANDROID_BUILD_TOOLS_DIR:-$SDK/build-tools/37.0.0}"
ANDROID_JAR="${ANDROID_JAR:-$SDK/platforms/android-37.0/android.jar}"

AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

SIGN_DIR="${KSOUND_SOUNDBOARD_SIGN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ksound-hub-v2/android}"
SIGN_ENV="$SIGN_DIR/signing.env"
KEYSTORE="${KSOUND_SOUNDBOARD_KEYSTORE:-$SIGN_DIR/ksound-soundboard.keystore}"

SIGNED_APK="$DIST_DIR/KSoundSoundboard.apk"
UNSIGNED_APK="$APP_DIR/unsigned.unaligned.apk"
ALIGNED_APK="$APP_DIR/aligned.apk"

GEN_DIR="$APP_DIR/gen"
CLASSES_DIR="$APP_DIR/classes"
DEX_DIR="$APP_DIR/dex"

for f in "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR"; do
  [[ -e "$f" ]] || { echo "Missing Android build dependency: $f" >&2; exit 1; }
done

mkdir -p "$SIGN_DIR"
chmod 700 "$SIGN_DIR"

generate_password() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
}

write_sign_env() {
  local pass="$1"
  local alias="$2"

  umask 077
  cat > "$SIGN_ENV" <<ENV
KSOUND_SOUNDBOARD_KEYSTORE_PASS='$pass'
KSOUND_SOUNDBOARD_KEY_PASS='$pass'
KSOUND_SOUNDBOARD_KEY_ALIAS='$alias'
ENV
  chmod 600 "$SIGN_ENV"
}

create_local_keystore() {
  local alias="ksound-soundboard"
  local pass
  pass="$(generate_password)"

  echo "No Android signing keystore found."
  echo "Generating local signing keystore automatically:"
  echo "  $KEYSTORE"

  keytool -genkeypair \
    -keystore "$KEYSTORE" \
    -storepass "$pass" \
    -keypass "$pass" \
    -alias "$alias" \
    -keyalg RSA \
    -keysize 2048 \
    -validity 36500 \
    -dname "CN=K-Sound Soundboard, OU=K-Sound Hub, O=Local, L=Local, ST=Local, C=BE" \
    >/dev/null

  chmod 600 "$KEYSTORE"
  write_sign_env "$pass" "$alias"
}

if [[ -f "$SIGN_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$SIGN_ENV"
fi

if [[ ! -f "$KEYSTORE" ]]; then
  create_local_keystore
  # shellcheck disable=SC1090
  source "$SIGN_ENV"
fi

KS_PASS="${KSOUND_SOUNDBOARD_KEYSTORE_PASS:-}"
KEY_PASS="${KSOUND_SOUNDBOARD_KEY_PASS:-$KS_PASS}"
KEY_ALIAS="${KSOUND_SOUNDBOARD_KEY_ALIAS:-ksound-soundboard}"

if [[ -z "$KS_PASS" ]]; then
  cat >&2 <<EOF2
Missing signing password in:
  $SIGN_ENV

Delete the broken signing files to auto-generate a fresh local key:
  rm -f "$KEYSTORE" "$SIGN_ENV"
  $0
EOF2
  exit 1
fi

if ! keytool -list -keystore "$KEYSTORE" -storepass "$KS_PASS" >/dev/null 2>&1; then
  cat >&2 <<EOF2
The configured Android keystore exists, but its stored password does not unlock it.

Keystore:
  $KEYSTORE

Signing env:
  $SIGN_ENV

For this personal remote, the simplest fix is to archive/delete both and rebuild:
  mv "$KEYSTORE" "$KEYSTORE.bad"
  mv "$SIGN_ENV" "$SIGN_ENV.bad"
  $0
EOF2
  exit 1
fi

if ! keytool -list -keystore "$KEYSTORE" -storepass "$KS_PASS" 2>/dev/null | grep -q "^${KEY_ALIAS},"; then
  DETECTED_ALIAS="$(
    LANG=C keytool -list -keystore "$KEYSTORE" -storepass "$KS_PASS" 2>/dev/null \
      | awk -F, '/PrivateKeyEntry/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1); print $1; exit}'
  )"

  if [[ -n "$DETECTED_ALIAS" ]]; then
    KEY_ALIAS="$DETECTED_ALIAS"
  else
    echo "Could not detect key alias in keystore: $KEYSTORE" >&2
    exit 1
  fi
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
echo "===== SIGN APK ====="
echo "Using keystore: $KEYSTORE"
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
