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
# Built into that libsndfile (bastibe/libsndfile-binaries, linux_build.sh for 1.2.2,
# soundfile 0.14.0): mpg123 is LGPL; LAME 3.100 is the same as ffmpeg's, attached above.
MPG123_VERSION=1.33.4
MPG123_SHA256=3ae8c9ff80a97bfc0e22e89fbcd74687eca4fc1db315b12607f27f01cb5a47d9
# PySide6 and shiboken6 (LGPL-3.0) have no source archive on PyPI.
PYSIDE_VERSION=6.12.0
PYSIDE_SHA256=099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751

# The pins must match what's installed, or the attached sources would be for other code.
cd "$ROOT"
uv run python - "$SNDFILE_VERSION" "$PYSIDE_VERSION" <<'PY'
import sys
import soundfile
from PySide6 import __version__ as pyside
want_sndfile, want_pyside = sys.argv[1], sys.argv[2]
assert soundfile.__libsndfile_version__ == want_sndfile, soundfile.__libsndfile_version__
assert pyside == want_pyside, pyside
PY

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
fetch "https://sourceforge.net/projects/mpg123/files/mpg123/$MPG123_VERSION/mpg123-$MPG123_VERSION.tar.bz2/download" \
  "mpg123-$MPG123_VERSION.tar.bz2" "$MPG123_SHA256"
fetch "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-$PYSIDE_VERSION-src/pyside-setup-everywhere-src-$PYSIDE_VERSION.tar.xz" \
  "pyside-setup-everywhere-src-$PYSIDE_VERSION.tar.xz" "$PYSIDE_SHA256"

# The copyleft Python packages (from uv.lock, SHA-256 checked) and SOURCES.txt.
uv run python tools/third_party.py --sources "$OUT"
echo "Sources in $OUT"
