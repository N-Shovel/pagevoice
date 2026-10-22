#!/usr/bin/env bash
# Collect the exact source of the GPL/LGPL programs bundled in PageVoice's builds, for
# each release (GPL-3.0 §6, LGPL-2.1 §6): ffmpeg and LAME (packaging/ffmpeg/build.sh),
# and espeak-ng (shipped inside espeakng-loader 0.2.4, built unmodified from tag 1.52.0).
#
#   packaging/sources.sh            # -> dist/sources/*.tar.*
#
# Versions and checksums are pinned here and in build.sh; a mismatch stops the release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/sources"
mkdir -p "$OUT"

# ffmpeg and LAME: the same pins as the build itself.
eval "$(grep -E '^(FFMPEG|LAME)_(VERSION|SHA256)=' "$ROOT/packaging/ffmpeg/build.sh")"
ESPEAK_VERSION=1.52.0
ESPEAK_SHA256=bb4338102ff3b49a81423da8a1a158b420124b055b60fa76cfb4b18677130a23

fetch() {  # url file sha256
  [ -f "$OUT/$2" ] || curl -fsSL --retry 3 -o "$OUT/$2" "$1"
  echo "$3  $OUT/$2" | sha256sum -c -
}
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
  "ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"
fetch "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
  "lame-$LAME_VERSION.tar.gz" "$LAME_SHA256"
fetch "https://github.com/espeak-ng/espeak-ng/archive/refs/tags/$ESPEAK_VERSION.tar.gz" \
  "espeak-ng-$ESPEAK_VERSION.tar.gz" "$ESPEAK_SHA256"
echo "Sources in $OUT"
