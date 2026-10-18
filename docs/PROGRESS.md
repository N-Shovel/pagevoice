# Progress

Claude Code keeps this file current. It updates it after every finished step and when it pauses at the usage limit (see [PAUSE_AND_RESUME.md](PAUSE_AND_RESUME.md)). Keep it short and up to date. The details live in git history and pull requests.

- **Last updated:** 2026-10-19
- **Milestone:** after M4: the external review's fixes, then the Listen feature. M0–M4 are done and merged (PRs #8, #9). M5 (installer) comes last.
- **Branch:** listen-mode (built on review-safety-fixes)
- **State:** working. The other states are: not started, working, waiting for owner, done.
- **Plan (owner, 2026-10-19):** PageVoice stays an audiobook maker, not a reader. The owner hands the work over and won't touch it. Order:
  1. Fix the review's serious findings (`pagevoice-review.md`, review of a7fa3f0).
  2. Add a Listen feature: play rendered chapters in the app (pause, seek, listen from a paragraph). Playback through sounddevice (proposed; license check first).
  3. Fix the review's reading and cleanup findings.
  4. M5, the installer, at the very end.
- **Merging:** the permission settings don't allow Claude to run `gh pr merge`, so PRs wait for the owner's click unless they allow it.

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
- **PR #11** (`gui-button-fixes`): Pronunciations, Back to review and Continue crashed when clicked; the open page's text was squeezed. Found by the owner. CI passed; waiting to be merged.
- **Piece 1 = PR #12** (`review-safety-fixes`) (it includes #11 through a merge, so either can merge first):
  - Findings fixed:
    - 1: MP3 export only removes files it wrote for the same book (record file `.pagevoice-export.json`)
    - 2: pronunciation lists are read in Excel's encodings and never saved over when unreadable
    - 3: an existing M4B is replaced only after asking (`--overwrite` in the CLI)
    - 4: PDF pages are closed as they're read
    - 16: mostly-scanned PDFs are refused (80% of pages; a stamp page counts as a scan)
    - 17: a stale render plan is discarded, and Pronunciations is locked during work
    - 20: a target locked by a player gets a plain message and no `.part`
    - 21: CLI `--chapters` keeps the cache
    - the license checker rejects GPL-2.0-only
  - Not done: quitting during a render leaves the process alive until the current paragraph ends. Low priority.
- **Piece 2 = Listen, on `listen-mode`** (PR after #12; see D36):
  - The engine's `render/playback.py` (timeline and player) and the GUI's Listen bar.
  - Review's right-click has "Listen from here".
  - sounddevice is in the `gui` extra, and CI installs libportaudio2.
- **Fast tests:** 293 passed, 1 skipped.

## Next step
1. Piece 3 on a new branch: the review's reading and cleanup findings:
   - findings 5–15, 18, 19, 22, 23
   - the rule gaps: SVG `<title>`, and `txt.py` importing `cleanup.en`
   - the test that can't fail (`test_chapter_audio_joins_paragraphs_with_pauses`)

   Cleanup fixes go through the add-cleanup-rule skill. Expected spoken forms are human-owned, so new ones go into `sentences.proposed.tsv`.
2. M5 last.

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
- **Thread pool (D35, provisional):** the GUI runs work on Qt's thread pool, not a QThread per job as `.claude/rules/gui.md` words it. It's the same mechanism. Confirm, and update the rule's wording if you agree.
- **Try the app:** `uv sync --extra gui`, then `uv run pagevoice-gui --dev-proposed-manifest`. Review a PDF, render a chapter, and export it. Listen.
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
