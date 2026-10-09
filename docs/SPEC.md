# PageVoice v1 specification

**In one line:** a desktop app for Windows and Linux that turns EPUB, text PDFs and TXT into an M4B or MP3s, using Kokoro on the CPU, English only, with automatic cleanup, a review screen, a pronunciation list and render-resume, released as GPL open source.

Why each choice was made is in [DECISIONS.md](DECISIONS.md). This file says *what*; that one says *why*.

## 1. Product

Local voice models are now good enough for audiobooks. The free tools are command-line projects and the polished apps are subscriptions. The hard part is cleaning page numbers, headers and footnotes out of PDFs, not the voice itself. PageVoice is a polished, free desktop app that does that cleanup well and works fully offline after first run.

## 2. Platforms and architecture

- Windows and Linux from day one, Mac later.
- Python with a PySide6 interface. Voice models run on ONNX Runtime, never PyTorch, which keeps the installer small.
- The **engine** (`src/pagevoice`) is its own package with a small command line (`pagevoice`) for testing. It never imports Qt. The **GUI** (`src/pagevoice_gui`) is just one way to drive it.
- **Installer:** small. The voice model is downloaded on first run and its SHA-256 checksum is verified. After that, everything works offline.

## 3. Inputs (v1)

| Input | v1 behaviour |
|---|---|
| EPUB | Supported. Parsed by hand: it is a zip of XHTML plus an OPF manifest. |
| PDF with a real text layer | Supported, via pypdfium2 or pdfplumber. |
| TXT | Supported. |
| Scanned PDF (no text layer) | Detected. Tell the user plainly that it needs OCR, which PageVoice doesn't do. Never read out garbage. |
| Multi-column PDF pages | Detected and flagged in review, like scanned pages. Proper column support comes later. |
| DOCX | Later. It's cheap to add. |
| MOBI / AZW3 | Not supported. Tell users to convert with Calibre. |
| DRM-protected files | Never touched. |

Banned libraries: PyMuPDF (`fitz`) and EbookLib, because both are AGPL. Ruff blocks the imports.

## 4. Cleanup

Cleanup runs automatically, then a **review screen** shows the result. Review is on by default for PDFs and optional for EPUBs, which are usually clean.

**Nothing is deleted silently.** Everything removed stays in the document as a removal with a reason. It shows dimmed in review, and the user can restore it.

PDF detection rules:

- **Headers and footers:** lines that repeat in the top or bottom strip of most pages.
- **Page numbers:** lone numbers in those strips.
- **Footnotes:** smaller text at the bottom of a page.
- **Captions and tables:** skipped by default (shown dimmed, restorable).
- **Hyphenation:** a word split at a line break is rejoined only if the joined form appears elsewhere in the book, or the hyphenated form doesn't. Otherwise "well-known" would become "wellknown".
- **Known extraction traps:** ligatures (fi, fl), drop caps ("T he"), small caps, soft hyphens, paragraphs that run across pages, and Word-exported PDFs.

Footnotes:

- Never read inline, because they break sentences.
- **Default:** remove the reference markers from sentences and move the notes to the end of the chapter.
- **Setting:** drop notes entirely.

PDF chapters:

1. Use the PDF's **top-level** bookmarks if it has them.
2. Otherwise, detect headings using two signals together: larger font size, and text patterns such as "Chapter N" or "CHAPTER".
3. In review, the user can merge, split and rename chapters.

## 5. Pronunciation

- There is a **global** list, plus **per-book** entries that override it.
- Each entry has a "sounds like" respelling, an optional raw-phoneme field, and a preview button.
- **Whole-word, case-sensitive option**, so "Polish" and "polish" stay separate.
- Lists are stored as a plain **TSV** file that people can import, export and edit in a spreadsheet, so one list can be shared across a book series. Accept files with or without a UTF-8 BOM, since Excel adds one.

## 6. Voice

- Kokoro is the default voice: Apache-2.0, small, about real-time or faster on an ordinary laptop CPU.
- CPU first. A GPU is an optional speed-up through DirectML on Windows (NVIDIA, AMD and Intel).
- No voice cloning in v1.
- The model file and voices file are hosted on **our own GitHub release**, with Kokoro's Apache license notice. URLs and checksums are pinned in `src/pagevoice/voice/model_manifest.json`, which only a human edits.
- **Model variant:** fp32 against int8. fp16 saves download size but not CPU time, so it's out of the running. The pick is decided by speed relative to real time, peak RAM, and blind A/B listening on `tests/voice/sentences.tsv`.

## 7. Text normalization and language

- English only in v1, but nothing is hard-coded. Each book stores a language.
- Text normalization (numbers, dates, money, abbreviations, Roman numerals) is **one module per language** (`normalize/en.py`, and so on).
- Languages are added one at a time, only after English is solid.

## 8. Rendering and output

- Rendering goes **paragraph by paragraph into a cache**. If the app crashes at chapter 17, it picks up there. Fixing one paragraph re-renders only that paragraph.
- A paragraph's cache key covers everything that changes its audio: normalized text, pronunciation entries applied, voice, model variant and speed.
- **Cache size:** Kokoro outputs 24 kHz audio, so the cache for a 10-hour book is about 1–2 GB even as FLAC. It lives in the per-user cache directory (platformdirs) under a size cap the user can change. A book's cache is cleared after a successful export unless the book is still being edited.
- **Default output:** one M4B with chapters, cover art and metadata, encoded as 64 kbps mono AAC. A 10-hour book comes to about 290 MB.
- **Option:** one MP3 per chapter.
- **ffmpeg is bundled.** It is a stripped-down LGPL-only build made in CI and signed with the app. It is never downloaded at runtime, and the system ffmpeg is never used.
  - Encoders: native AAC and LAME (MP3).
  - Output formats: MP4/M4B (ffmpeg's `ipod` muxer) and MP3.
  - Input formats: WAV and FLAC, plus the concat and ffmetadata demuxers and image input for cover art.
  - No `--enable-gpl` and no `--enable-nonfree`.

## 9. Packaging and release

- **Windows:** PyInstaller in **one-folder** mode inside an Inno Setup installer. Never one-file mode, because antivirus tools flag it constantly.
- **Linux:** an AppImage, built on `ubuntu-22.04` so it runs on older distros.
- No .deb or Flatpak in v1.
- **Release workflow:** reuse the structure of `folder-tracker/.github/workflows/release.yml`.
  - Pushing a `v*` tag builds the Windows and Linux jobs, and both attach to the same GitHub release.
  - SignPath signing switches on by itself once the `SIGNPATH_API_TOKEN` secret and the `SIGNPATH_ORGANIZATION_ID` variable exist.
- **Repository:** `N-Shovel/pagevoice`, licensed GPL-3.0.
- **SignPath Foundation:** apply early, because each project is approved separately.
- **`main` is protected:** changes arrive only through pull requests. CI (`.github/workflows/ci.yml`) runs ruff, the fast tests and the license check on Windows and on Ubuntu 22.04, and both jobs must pass. Force pushes and deleting `main` are blocked. Releases bump the version on a `release/vX.Y.Z` branch and tag the merge commit.

## 10. Benchmarks and test machines

- **Real numbers:** the developer laptop, `laptop-tlc3d2rv`. It decides the user experience: progress display, pause and resume, overnight runs.
- **Repeatable baseline:** the same benchmark on a GitHub Actions runner, tracked in CI so slowdowns show up.
- **Linux:** VirtualBox VMs for packaging and smoke tests only, never for speed numbers. Use a clean Ubuntu 22.04 VM, not Kali, whose libraries are newer than most users have.

## 11. Test material

- **Golden corpus** (`tests/corpus/`): public-domain EPUBs and PDFs, plus trap PDFs, with hand-checked expected text for a few pages of each. Every cleanup change runs against all of them. Copyrighted books live in `tests/corpus/private/`, which git ignores. See [tests/corpus/README.md](../tests/corpus/README.md).
- **Voice sentence list** (`tests/voice/sentences.tsv`): numbers, dates, money, abbreviations, Roman numerals, dialogue, long sentences, names and heteronyms, each with its expected spoken form.
- **Round-trip check:** render the audio, transcribe it with faster-whisper (dev-only, never shipped) and diff the transcript against the expected text. This catches skipped sentences, wrongly read numbers and garbled chunks. How natural it sounds, and how names come out, is checked by a human listening.

## 12. Milestones (proposed order)

| # | Milestone | Done when |
|---|---|---|
| M0 | Week one: Kokoro benchmark | fp32 and int8 measured on the laptop and the CI runner, blind A/B done, G2P chosen (O1), model and voices hosted with a manifest, Python 3.13 builds confirmed for onnxruntime, PySide6, PyInstaller and the chosen G2P (otherwise drop to 3.12) |
| M1 | Ingest and cleanup | TXT, EPUB and PDF become chapters of paragraphs with removal spans. Scanned and multi-column pages are detected. Golden corpus passes. |
| M2 | Speech | English normalizer passes the sentence list, pronunciation lists work, and the paragraph cache renders and resumes |
| M3 | Export | CI-built ffmpeg; M4B with chapters, cover and metadata; MP3 per chapter |
| M4 | GUI | Import → review (dimmed removals, restore, chapter edits) → render with progress, pause and resume → export, without blocking the UI |
| M5 | Release | PyInstaller one-folder build, Inno Setup, AppImage, first-run model download, tag-driven release, SignPath |

At the end of each milestone, run the `spec-reviewer` agent against this file and DECISIONS.md.

## 13. Open questions

| # | Question | Notes |
|---|---|---|
| O1 | Which G2P (text-to-phonemes) for Kokoro? | misaki (Kokoro's own, Apache-2.0) uses spaCy's grammar tagging to choose between heteronyms ("polish/Polish", "read/read", "lead/lead"); espeak-ng via phonemizer (GPL-3.0, fine for us) mostly can't. spaCy plus its English model is what the extra installer size buys. Decide in M0 with the six `het-*` rows of `tests/voice/sentences.tsv`. |
| O4 | Default Kokoro voice and speed | Pick after the A/B listening in M0. |

Resolved, 2026-10-09:

- **O2, license variant:** GPL-3.0-or-later (D1).
- **O3, pronunciation file format:** TSV, BOM accepted (D15).
- **O5, disk locations:** platformdirs, with a capped render cache (D26).
