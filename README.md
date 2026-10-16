# PageVoice

Turn EPUB, PDF and TXT books into audiobooks on your own computer, without an internet connection.

PageVoice cleans up the book first. It takes out page numbers, running headers, footnote markers and captions, and shows you what it removed so you can bring anything back. Then it reads the book aloud with the [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) voice on your CPU, and saves an M4B audiobook with chapters or one MP3 per chapter.

> **Status:** early development, no release yet. You can run it from source. Installers for Windows and Linux are planned.

## Features

- **Books:**
  - EPUB.
  - PDFs with real text. Scanned PDFs are detected and refused plainly; they need OCR first.
  - Plain text.
- **Review screen:** every removal is shown dimmed with its reason, and one click restores it. You can rename, merge and split chapters.
- **Pronunciation lists:** fix how names are said, for one book or for all books. Lists are plain TSV files you can edit in a spreadsheet and share.
- **Pause and resume:** rendering carries on where it stopped, even after closing the app.
- **Output:** an M4B with chapters, cover and title, or one MP3 per chapter.
- **Offline:** the only download is the voice itself (about 330 MB), once, checked against a pinned checksum.

English only for now.

## Run it from source

You need [uv](https://docs.astral.sh/uv/) and Git. uv installs the right Python (3.12) by itself.

```
git clone https://github.com/N-Shovel/pagevoice.git
cd pagevoice
uv sync --extra gui
uv run pagevoice-gui --dev-proposed-manifest
```

Then open a book. The first time you press Render, PageVoice offers to download the voice.

`--dev-proposed-manifest` is needed until the voice files are published as a PageVoice release.

### Export (M4B or MP3)

Exporting needs PageVoice's own build of ffmpeg, which is never taken from your system. To build it, run `packaging/ffmpeg/build.sh` on Linux, or in MSYS2 on Windows. You can also download the `ffmpeg-Linux` or `ffmpeg-Windows` artifact from a run of the `ffmpeg` workflow and unpack it into `packaging/ffmpeg/out/`.

### Command line

```
uv run pagevoice info book.pdf                                  # chapters and what cleanup removed
uv run pagevoice render book.pdf --out chapters/ --dev-proposed-manifest   # WAV per chapter
uv run pagevoice export book.epub --out book.m4b --dev-proposed-manifest   # audiobook
```

Run `uv run pagevoice --help` for every option.

## Not supported

- MOBI and AZW3: convert them to EPUB with [Calibre](https://calibre-ebook.com/) first.
- DRM-protected books.
- Scanned PDFs without a text layer.
- Languages other than English.

## For developers

- `docs/SPEC.md`: what PageVoice does.
- `docs/DECISIONS.md`: why it's built this way.
- `docs/PROGRESS.md`: where the work stands.

Tests: `uv run pytest -m "not slow"`.

## License

[GPL-3.0](LICENSE).

The Kokoro voice model is Apache-2.0. The bundled ffmpeg is an LGPL-only build.
