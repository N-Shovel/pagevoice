# PageVoice

A desktop app (Windows and Linux; Mac later) that turns EPUB, text PDFs and TXT into audiobooks (M4B, or MP3 per chapter), fully offline, using the Kokoro voice on the CPU through ONNX Runtime. The hard part is cleaning PDFs (headers, page numbers, footnotes), not the voice. Licensed GPL-3.0 and released on GitHub (`N-Shovel/pagevoice`).

- **What to build:** [docs/SPEC.md](docs/SPEC.md).
- **Why it's built that way:** [docs/DECISIONS.md](docs/DECISIONS.md). Those decisions are settled. Don't re-propose rejected options (PyMuPDF, Electron or Tauri, PyTorch, XTTS, runtime ffmpeg download, PyInstaller one-file, and so on). If one looks wrong, ask the owner; don't route around it.

## v1 scope

**In:** EPUB, PDF with a text layer, TXT · automatic cleanup plus a review screen · global and per-book pronunciation lists · English only (language stored per book) · Kokoro on CPU, DirectML optional on Windows · paragraph render cache with resume · M4B (chapters, cover, metadata) or MP3 per chapter · Inno Setup installer and AppImage.

**Out:**
- **Detect and tell the user plainly:** OCR / scanned PDFs, two-column layouts (flagged in review).
- **Point users to Calibre:** MOBI, AZW3.
- **Never in v1:** DRM (never touched), voice cloning, languages other than English, .deb and Flatpak.

## Rules you would otherwise break

1. **The engine never imports Qt.** `src/pagevoice` must not import PySide6 or `pagevoice_gui`. The GUI calls the engine, never the other way round. Checked by `tests/test_architecture.py`.
2. **Cleanup never deletes anything silently.** Every removal keeps the original text, its reason and its location, so the review screen can show it dimmed and the user can restore it.
3. **No AGPL, non-commercial or unknown-license packages.** No PyMuPDF/`fitz`, no EbookLib, no PyTorch. Add any dependency only through the `add-dependency` skill, and run `tools/check_licenses.py` after.
4. **Copyrighted test books never get committed.** They live in `tests/corpus/private/` (git-ignored). Only public-domain books, and PDFs we made ourselves, go in `tests/corpus/public/`.
5. **Golden answers are human-owned.** You can't edit `tests/corpus/**/expected/`, `tests/voice/sentences.tsv` or `src/pagevoice/voice/model_manifest.json`; a hook blocks it. When a test fails, fix the code. If an expectation is truly wrong, write a proposal (`candidate/` or `*.proposed.*`) and ask.
6. **Fully offline after first run.** The only network access in the app is the first-run model download, verified against the manifest checksum.
7. **No language hard-coding outside language modules.** English rules live in `normalize/en.py`-style modules keyed by the book's language.

## Layout

```
src/pagevoice/          engine + CLI. Planned subpackages:
                        ingest/ cleanup/ normalize/ pronounce/ voice/ render/ export/
src/pagevoice_gui/      PySide6 app
tests/                  unit tests; corpus/ (golden books); voice/sentences.tsv
tools/                  dev scripts (licenses, benchmark, round-trip)
benchmarks/history.csv  benchmark log (audio in benchmarks/out/, git-ignored)
packaging/              PyInstaller spec, Inno Setup, AppImage, ffmpeg build (planned)
docs/                   SPEC.md, DECISIONS.md
```

## Commands

| Task | Command |
|---|---|
| Set up / update the environment | `uv sync` |
| Tests (all) | `uv run pytest` |
| Tests (skip slow ones that need the model) | `uv run pytest -m "not slow"` |
| Lint | `uv run ruff check .` |
| Formatting | `uv run ruff format --check .` |
| License check | `uv run python tools/check_licenses.py` |
| CLI | `uv run pagevoice --help` |
| Benchmark (planned, M0) | `uv run python tools/benchmark.py` (see the `benchmark` skill) |
| Round-trip check (planned) | `uv run --group roundtrip python tools/roundtrip.py` (see the `roundtrip-check` skill) |
| Build (planned, M5) | `uv run pyinstaller packaging/pagevoice.spec` |

After every `.py` edit, a hook runs `ruff format` and `ruff check` on that file and shows you any remaining problems. Fix them before moving on.

## How to work here

- **Skills:**
  - `add-cleanup-rule`: start from a failing book.
  - `add-dependency`: license first.
  - `benchmark`
  - `roundtrip-check`
  - `release`: user-only, via `/release`.
- **At the end of each milestone** in SPEC.md §12, run the `spec-reviewer` agent and fix what it finds before calling the milestone done.
- **Audio:** you can't hear it. Never claim the voice "sounds good". Report round-trip numbers, and ask the owner to listen for naturalness and names.
- **Commits and PRs:** no Claude or AI attribution of any kind.
