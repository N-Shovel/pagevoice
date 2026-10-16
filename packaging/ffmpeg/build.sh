#!/usr/bin/env bash
# Build the small LGPL-only ffmpeg that PageVoice bundles (SPEC §8, DECISIONS D18).
#
#   packaging/ffmpeg/build.sh [OUT_DIR]        (default: packaging/ffmpeg/out/<os>)
#
# Runs on Linux (ubuntu-22.04 in CI, for old-glibc compatibility) and on Windows inside
# MSYS2's MINGW64 shell. Sources are downloaded from their official sites and checked
# against the SHA-256 below before anything is built.
#
# Only what PageVoice uses is enabled:
#   encoders  aac (native), libmp3lame        muxers    ipod, mp4, mp3
#   decoders  pcm_s16le, flac, png, mjpeg     demuxers  wav, flac, concat, ffmetadata,
#   filters   aresample, aformat, anull                 image2, png/jpeg pipes
#   protocols file, pipe
# Never --enable-gpl, never --enable-nonfree. The script checks the result says LGPL.
set -euo pipefail

FFMPEG_VERSION=8.1.3
FFMPEG_SHA256=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e

HERE="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*) OS=windows; EXE=.exe ;;
  Linux) OS=linux; EXE= ;;
  Darwin) OS=macos; EXE= ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
OUT="${1:-$HERE/out/$OS}"
WORK="${WORK:-$HERE/work}"
PREFIX="$WORK/prefix"
JOBS="$(nproc 2>/dev/null || echo 4)"
mkdir -p "$WORK" "$PREFIX" "$OUT/bin" "$OUT/licenses"

fetch() {  # url file sha256
  if [ ! -f "$WORK/$2" ]; then
    curl -fsSL --retry 3 -o "$WORK/$2.part" "$1"
    mv "$WORK/$2.part" "$WORK/$2"
  fi
  echo "$3  $WORK/$2" | sha256sum -c -
}

fetch "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
  "lame-$LAME_VERSION.tar.gz" "$LAME_SHA256"
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
  "ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"

# LAME (LGPL-2.0-or-later), static library only.
rm -rf "$WORK/lame-$LAME_VERSION"
tar -xzf "$WORK/lame-$LAME_VERSION.tar.gz" -C "$WORK"
(
  cd "$WORK/lame-$LAME_VERSION"
  ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-frontend \
    --disable-decoder --disable-gtktest --enable-nasm=no
  make -j"$JOBS"
  make install
)

# ffmpeg, LGPL-2.1-or-later configuration.
rm -rf "$WORK/ffmpeg-$FFMPEG_VERSION"
tar -xJf "$WORK/ffmpeg-$FFMPEG_VERSION.tar.xz" -C "$WORK"
EXTRA_LDFLAGS="-L$PREFIX/lib"
[ "$OS" = windows ] && EXTRA_LDFLAGS="$EXTRA_LDFLAGS -static"
# --disable-autodetect also drops threads and zlib, so both are named here. zlib (zlib
# licence) is needed by the PNG decoder, which the muxers need for a PNG cover's size.
THREADS="--enable-pthreads"
[ "$OS" = windows ] && THREADS="--enable-w32threads"
(
  cd "$WORK/ffmpeg-$FFMPEG_VERSION"
  ./configure \
    --prefix="$PREFIX" \
    --disable-everything --disable-autodetect --disable-network --disable-doc \
    --disable-debug --disable-ffplay --disable-ffprobe --disable-shared --enable-static \
    --enable-small --disable-x86asm --enable-ffmpeg --enable-avfilter --enable-swresample \
    --enable-libmp3lame --enable-zlib $THREADS \
    --enable-encoder=aac,libmp3lame \
    --enable-decoder=pcm_s16le,flac,png,mjpeg \
    --enable-muxer=ipod,mp4,mp3 \
    --enable-demuxer=wav,flac,concat,ffmetadata,image2,image_png_pipe,image_jpeg_pipe \
    --enable-parser=aac,mpegaudio,flac,png,mjpeg \
    --enable-filter=aresample,aformat,anull \
    --enable-protocol=file,pipe \
    --extra-cflags="-I$PREFIX/include" --extra-ldflags="$EXTRA_LDFLAGS"
  make -j"$JOBS"
  cp "ffmpeg$EXE" "$OUT/bin/ffmpeg$EXE"
  cp COPYING.LGPLv2.1 "$OUT/licenses/ffmpeg-COPYING.LGPLv2.1"
  cp LICENSE.md "$OUT/licenses/ffmpeg-LICENSE.md"
)
cp "$WORK/lame-$LAME_VERSION/COPYING" "$OUT/licenses/lame-COPYING"

# Everything the exporters use must be in the binary (configure only warns when it drops a
# component whose dependency is missing).
for need in "decoders png" "decoders mjpeg" "decoders flac" "encoders aac"   "encoders libmp3lame" "muxers ipod" "muxers mp3"; do
  set -- $need
  if ! "$OUT/bin/ffmpeg$EXE" -hide_banner "-$1" | grep -qE "^ [A-Z.]+ +$2( |$)"; then
    echo "ffmpeg was built without $2 ($1); refusing to ship it" >&2
    exit 1
  fi
done

# The bundled binary must be LGPL: check what it says about itself.
"$OUT/bin/ffmpeg$EXE" -hide_banner -L | tee "$OUT/licenses/ffmpeg-L.txt" | head -3
if ! grep -q "Lesser General Public" "$OUT/licenses/ffmpeg-L.txt"; then
  echo "ffmpeg does not report an LGPL licence; refusing to ship it" >&2
  exit 1
fi
if "$OUT/bin/ffmpeg$EXE" -hide_banner -buildconf | grep -E -- "--enable-(gpl|nonfree)"; then
  echo "ffmpeg was configured with GPL or nonfree parts; refusing to ship it" >&2
  exit 1
fi
{
  echo "ffmpeg $FFMPEG_VERSION (sha256 $FFMPEG_SHA256), https://ffmpeg.org/releases/"
  echo "LAME $LAME_VERSION (sha256 $LAME_SHA256), https://lame.sourceforge.io/"
  echo "Built by packaging/ffmpeg/build.sh. Source for both is at the URLs above;"
  echo "the build script and configure flags are in the PageVoice repository."
} > "$OUT/licenses/SOURCES.txt"
echo "Built $OUT/bin/ffmpeg$EXE"
