#!/usr/bin/env bash
# Collect the exact source of the GPL/LGPL programs bundled in PageVoice's builds, for
# each release (GPL-3.0 §6, LGPL-2.1 §6): ffmpeg and LAME (packaging/ffmpeg/build.sh),
# espeak-ng (shipped inside espeakng-loader 0.2.4, built unmodified from tag 1.52.0),
# libsndfile (inside soundfile), and every copyleft Python package (tools/third_party.py).
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
SNDFILE_VERSION=1.2.2  # the one inside the soundfile wheel (soundfile.__libsndfile_version__)
SNDFILE_SHA256=3799ca9924d3125038880367bf1468e53a1b7e3686a934f098b7e1d286cdb80e

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
fetch "https://github.com/libsndfile/libsndfile/releases/download/$SNDFILE_VERSION/libsndfile-$SNDFILE_VERSION.tar.xz" \
  "libsndfile-$SNDFILE_VERSION.tar.xz" "$SNDFILE_SHA256"

# The copyleft Python packages (from uv.lock, SHA-256 checked) and SOURCES.txt.
cd "$ROOT"
uv run python tools/third_party.py --sources "$OUT"
echo "Sources in $OUT"
