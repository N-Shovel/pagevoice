#!/usr/bin/env bash
# Wrap the PyInstaller one-folder build (dist/PageVoice/) into an AppImage (SPEC §9).
# Build on ubuntu-22.04 so it runs on older distros (.claude/rules/packaging.md).
#
#   packaging/linux/build-appimage.sh 1.0.0
#
# Output: dist/PageVoice-<version>-x86_64.AppImage
# appimagetool and the AppImage runtime are build tools, pinned by version and SHA-256
# like the ffmpeg sources; nothing is downloaded when the app runs.
set -euo pipefail

VERSION="${1:-0.0.0-dev}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TOOLS="$ROOT/build/appimage-tools"
APPDIR="$ROOT/build/PageVoice.AppDir"

APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

[ -x "$ROOT/dist/PageVoice/PageVoice" ] || { echo "Build dist/PageVoice first (pyinstaller)" >&2; exit 1; }

fetch() {  # url file sha256
  if [ ! -f "$TOOLS/$2" ]; then
    curl -fsSL --retry 3 -o "$TOOLS/$2" "$1"
  fi
  echo "$3  $TOOLS/$2" | sha256sum -c -
}
mkdir -p "$TOOLS"
fetch "$APPIMAGETOOL_URL" appimagetool "$APPIMAGETOOL_SHA256"
fetch "$RUNTIME_URL" runtime "$RUNTIME_SHA256"
chmod +x "$TOOLS/appimagetool"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a "$ROOT/dist/PageVoice" "$APPDIR/usr/lib/pagevoice"
cp "$ROOT/packaging/icons/pagevoice.png" "$APPDIR/pagevoice.png"
cp "$HERE/pagevoice.desktop" "$APPDIR/pagevoice.desktop"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/pagevoice/PageVoice" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

OUT="$ROOT/dist/PageVoice-$VERSION-x86_64.AppImage"
# APPIMAGE_EXTRACT_AND_RUN: CI runners have no FUSE to mount appimagetool itself.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 VERSION="$VERSION" \
  "$TOOLS/appimagetool" --runtime-file "$TOOLS/runtime" "$APPDIR" "$OUT"
echo "Built $OUT"
