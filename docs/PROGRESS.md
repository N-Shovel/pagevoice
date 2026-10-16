# Progress

Claude Code keeps this file current. It updates it after every finished step and when it pauses at the usage limit (see [PAUSE_AND_RESUME.md](PAUSE_AND_RESUME.md)). Keep it short and up to date. The details live in git history and pull requests.

- **Last updated:** 2026-10-16
- **Milestone:** M4, GUI (draft PR #8). M0–M3 are done except the owner items below.
- **Branch:** m4-gui
- **State:** working. The other states are: not started, working, waiting for owner, done.
- **Plan (owner, 2026-10-16):** work through M0–M4 without waiting, one PR per milestone, spec-reviewer at the end of each, merge when CI passes. Don't start M5. Choices that depend on the owner are made from the numbers and marked "provisional" in DECISIONS.md.

## Done
- Project setup, CI and branch protection (PR #1).
- Usage pause and "continue" (PR #2).
- M0 (PR #3):
  - Python 3.12, because misaki declares `<3.13` (D24 update). The other packages all have 3.13 builds.
  - Voice engine in `src/pagevoice/voice/`: manifest, first-run download with a hard SHA-256 check, English G2P, and Kokoro on ONNX Runtime.
  - `model_manifest.proposed.json`: fp32, int8 and 28 English voices.
  - `tools/benchmark.py` with blind A/B pairs, `tools/roundtrip.py`, and a CI benchmark workflow.
  - Benchmarks for the laptop and both CI runners are in `benchmarks/history.csv`.
  - Provisional picks:
    - G2P: misaki with espeak fallback (D29).
    - Model variant: fp32 (D30).
    - Default voice: af_heart at speed 1.0 (D31).
  - The spec-reviewer findings are fixed:
    - The G2P can never pip-download the spaCy model.
    - Text that would be dropped is warned about.
    - Requesting DirectML fails loudly if it isn't really running.
    - British English is detected from any spelling of the code.
    - Benchmark comparisons match on the CPU too.

- M1 (PRs #4 and #5, merged by the owner):
  - Readers: TXT, EPUB (parsed by hand) and PDF (pdfplumber).
  - Removals, all restorable:
    - headers, footers and page numbers
    - footnotes (moved to the chapter's end) and their markers
    - captions, tables, contents and boilerplate
    - figures, non-linear EPUB text and line-break hyphens
  - Repairs: drop caps, small caps, ligatures and soft hyphens.
  - Scanned and multi-column pages are flagged, and non-English books are refused plainly.
  - Corpus: 7 trap PDFs and 5 public books. 23 candidate pages match.
  - The spec-reviewer's findings are fixed.
  - The resilient corpus fetch missed the merge; it's on `m2-speech`.

- M2 (PR #6, merged by the owner):
  - English normalizer, pronunciation lists, paragraph render cache, renderer, CLI `render`.
  - The spec-review findings are fixed (D33).

- M3 (PR #7, merged by the owner):
  - Bundled LGPL ffmpeg built in CI.
  - M4B with chapters, cover and tags, or MP3 per chapter.
  - CLI `export`.
  - The spec-review fixes are in D34.

## In progress
- **M4: draft PR #8** from `m4-gui`. CI passed on both OSes, and the 15 GUI tests ran headless on Ubuntu too.
  - Engine (no Qt, tested):
    - `edit.py`: restore, rename, merge, split.
    - `project.py`: the saved review per book, and the per-book pronunciation list path.
    - `speak()` for previews.
  - GUI (`pagevoice-gui`, the `gui` extra with PySide6-Essentials):
    - Open: PDFs go to review first; EPUB and TXT skip it.
    - Review: dimmed removals with reasons, click to restore, chapter rename, merge and split, flagged pages.
    - Pronunciations: the book's list and the list for all books, with preview and TSV import/export.
    - Render: progress, time left, pause, resume and stop.
    - Export, and the first-run voice download.
  - All slow work runs through `pagevoice_gui/tasks.py` workers.
  - The spec-reviewer was started for M4. Its findings are next.
- **Fast tests:** 239 passed, 3 skipped.

## Next step
1. Fix the M4 spec-reviewer findings (re-run it if its results were lost), then mark PR #8 ready.
2. Don't start M5.

## Waiting on the owner
- **Model manifest:**
  - Check `src/pagevoice/voice/model_manifest.proposed.json`.
  - Create the `models-kokoro-v1.0` GitHub release with those files and Kokoro's Apache-2.0 notice.
  - Move the file to `model_manifest.json`.
  - Until then, dev tools download from the pinned source URLs.
- **Blind A/B listening:** the fp32/int8 pairs are in `benchmarks/out/2026-10-16-ab/` (only on the laptop; that folder is git-ignored). Listen, note a preference per pair, and only then open `key.json`. That settles D30.
- **Listen to a rendered chapter:**
  - Run `uv run pagevoice render tests/corpus/public/trap-lantern/book.pdf --out out --chapters 3 --dev-proposed-manifest`.
  - Check the pauses (D33) and the reading of numbers and abbreviations.
  - "'Tis" comes out as "tease"; it's a candidate for the global pronunciation list.
- **Listen to the voices** (`benchmarks/out/roundtrip-2026-10-16-*/audio/`) for D31, and to the names and heteronyms for D29.
- **espeakng-loader in `REVIEWED`** in `tools/check_licenses.py` (the skill asks for the owner's OK).
- **Golden pages:**
  - Check the drafts in each corpus book's `candidate/` folder against the printed pages, fix them, and move them into the human-owned folder next to it.
  - Until then the golden test skips, and M1's "golden corpus passes" can't be shown.
  - Where the drafts come from:
    - Trap PDFs: the text they were typeset from.
    - Real books: PageVoice's output, checked against page images by Claude.
    - The OCR books keep the text layer's spelling errors.
- **Notes in audio:** should notes at a chapter's end get a spoken "Notes" heading or a longer pause? (M2 review, item 16)
- **Stress in respellings:** capitals in a "sounds like" respelling no longer mark stress (misaki never used them). Is that OK, or should the GUI preview steer people to the phonemes column for stress? (D33)
- **Years with context (D33):** "had 1500 soldiers" is now a count, and "1914 changed everything" or "It was 1945." are years. Listen for misreadings in real books.
- **Copy-protected PDFs (D32, provisional):** a PDF that forbids copying text is refused. Say if that's too strict.
- **Installer size:** the G2P stack (spaCy + English model + espeak-ng) is well over the skill's ~20 MB line for runtime packages. SPEC O1 expected this, but it needs the owner's OK.

## Notes for next time
- **GUI screenshots:** run with `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:/Windows/Fonts` (without fonts, the offscreen platform draws boxes), then save `window.grab()`.
- **Cleanup, seen in review:** in trap-lantern chapter I, the subtitle joins the first line ("The Tower Stood on a ledge…"). It's M1 cleanup, so check it against the golden pages.
- **Status line (README step 7):** no state file appeared in this client (the VS Code chat panel), so the 90% pause doesn't fire here. Use `claude` in VS Code's terminal for long runs. PROGRESS.md and "continue" still work.
- **Dependencies:** `uv add` is on the ask list. To avoid prompts while the owner is busy, dependencies were written to pyproject.toml and installed with `uv sync`, after the same license check.
- **For M2:** misaki also reads numbers itself (num2words). M2's `normalize/en.py` must run first, so misaki only ever sees normalized text, with a test that numbers aren't read twice. The render cache should also record the text the G2P couldn't pronounce, per paragraph.
- **For M4:** `ensure_file` hashes the whole model on each call (326 MB for fp32), so it must never run on the UI thread.
- **For M5:** check that `en_core_web_sm` is bundled in the PyInstaller build. The G2P refuses to download it, and reports it missing instead.
- **CI benchmark rows** come from the workflow artifact. Copy the `gha-*` rows into `benchmarks/history.csv` in the next PR that touches the voice code.
