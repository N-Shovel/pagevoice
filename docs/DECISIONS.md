# Decisions

Why PageVoice is built the way it is. These are settled. Don't re-argue them in a new session. To change one, ask the project owner, then edit the entry and add a dated note saying what changed and why.

Format: **decision**, then *why*, then the alternatives that were rejected.

---

### D1. License: GPL-3.0-or-later (decided 2026-10-09)
Most Kokoro setups use espeak-ng to turn text into phonemes, and espeak-ng is GPL, as is Piper now. Licensing the app GPL avoids the conflict. SignPath Foundation only signs open-source projects, so this also gets free code signing.
"Or later" is the usual choice for GPL projects, and it stays compatible with GPL-3.0-only dependencies.
*Rejected:* a closed or commercial version later. It would mean replacing the GPL parts and losing free signing, so it is ruled out now.

### D2. Python + PySide6 (2026-10-09)
The engine is Python anyway, so the GUI is too.
*Rejected:* Tauri and Electron. We'd still ship Python alongside them, so we'd maintain two runtimes just for a nicer settings screen.

### D3. ONNX Runtime, never PyTorch (2026-10-09)
PyTorch makes the installer gigabytes. Ruff bans `import torch`. An optional GPU speed-up on Windows goes through DirectML, which covers NVIDIA, AMD and Intel.

### D4. Engine and GUI are separate packages (2026-10-09)
`pagevoice` (engine and small CLI) never imports Qt. `pagevoice_gui` is just one way to drive it. This is enforced by `tests/test_architecture.py`.

### D5. No AGPL libraries: no PyMuPDF, no EbookLib (2026-10-09)
Both are AGPL. Use pypdfium2 or pdfplumber for PDFs (pdfplumber chosen in M1, D32). Parse EPUB ourselves, since it's just a zip of XHTML files plus an OPF manifest. Ruff bans `fitz`, `pymupdf` and `ebooklib`, and `tools/check_licenses.py` fails on any AGPL, non-commercial or unknown license.

### D6. Inputs in v1: EPUB, text PDFs, TXT (2026-10-09)
- **No OCR.** Detect scanned PDFs (no text layer) and say so plainly instead of reading out garbage.
- **No MOBI or AZW3.** Point users to Calibre.
- **DRM is never touched.**
- **DOCX** comes later; it's cheap.

### D7. Kokoro is the default voice; CPU first (2026-10-09)
Kokoro is Apache-licensed and small. It runs roughly real-time or faster on an ordinary laptop CPU, and it is close to the big models in quality.

### D8. No voice cloning in v1 (2026-10-09)
XTTS v2 and F5-TTS are licensed for non-commercial use only. Cloning raises consent problems, and both need a GPU.
*If cloning is ever added:* Chatterbox (MIT).

### D9. Model download, hosting and variant (2026-10-09)
- The voice model is downloaded on first run and its SHA-256 is checked. It is never bundled.
- The model and voices files are hosted on our own GitHub release, with Kokoro's Apache license notice, so URLs and checksums never change under us.
- **Variant contest is fp32 against int8.** fp16 saves download size, not CPU time.
- **Judged by:** speed relative to real time, peak RAM, and blind A/B listening on a fixed sentence set.

### D10. Automatic cleanup with review; nothing deleted silently (2026-10-09)
- Everything removed shows dimmed in review and can be restored.
- Review is shown by default for PDFs and is optional for EPUBs, which are usually clean.

### D11. Footnotes: move to the end of the chapter by default (2026-10-09)
- Reference markers are removed from sentences, and notes go to the end of the chapter.
- A setting drops notes entirely.
- Notes are never read inline, because they break sentences.

### D12. Hyphens are rejoined only with evidence (2026-10-09)
A word split at a line break is rejoined only if the joined form appears elsewhere in the book, or the hyphenated form doesn't. Otherwise "well-known" becomes "wellknown".

### D13. PDF chapters (2026-10-09)
1. Top-level bookmarks only.
2. Otherwise, font size plus "Chapter N" / "CHAPTER" text patterns as two signals.
3. The user can fix chapters in review.

### D14. Multi-column pages are flagged, not handled (2026-10-09)
v1 targets books. Multi-column pages are detected and flagged in review, the same way scanned pages are. Captions and tables are skipped by default, but still shown dimmed.

### D15. Pronunciation lists: global plus per-book (2026-10-09)
Mispronounced character names are the biggest complaint about TTS audiobooks.
- Per-book entries override the global list.
- A whole-word, case-sensitive option keeps "Polish" and "polish" apart.
- Lists are plain files people can import, export and share across a book series.
- **Format: TSV** (2026-10-09). Users can edit it in a spreadsheet; TOML is for programmers. Files are read with or without a UTF-8 BOM, because Excel adds one.

### D16. Paragraph-level render cache (2026-10-09)
The cache matters more than the output format. A crash at chapter 17 resumes at chapter 17, and fixing one paragraph re-renders only that paragraph.

### D17. M4B by default, MP3 per chapter as an option; 64 kbps mono AAC (2026-10-09)
- M4B carries chapters, cover art and metadata. MP3 export costs almost nothing extra.
- 64 kbps mono AAC is plenty for speech: a 10-hour book is about 290 MB.

### D18. Bundled, CI-built, LGPL-only ffmpeg (2026-10-09)
We build a stripped-down ffmpeg in CI with only what we need: native AAC, LAME, MP4 and MP3 output, WAV and FLAC input. That's a few MB, bundled and signed with the app. The build is LGPL-only, with no GPL or nonfree options.
*Rejected:* downloading ffmpeg at runtime, and using the system ffmpeg on Linux. Different ffmpeg versions mean bugs we can't reproduce.

### D19. English only, but language-aware from the start (2026-10-09)
- A language is stored per book, and text normalization is one module per language.
- Kokoro supports other languages, but quality outside English is uneven, and the normalization rules are where most of the work is.
- Languages are added one at a time after English is solid.

### D20. Packaging (2026-10-09)
- **Windows:** PyInstaller **one-folder** mode inside an Inno Setup installer. Never one-file mode, because antivirus tools flag it constantly.
- **Linux:** an AppImage, built on `ubuntu-22.04` so it runs on older distros.
- No .deb or Flatpak in v1.

### D21. Release pipeline reuses Folder Tracker's (2026-10-09)
- Same structure as `N-Shovel/folder-tracker/.github/workflows/release.yml`: pushing a tag builds the Windows and Linux jobs, both attach to the same GitHub release, and SignPath signing switches on once the secrets exist.
- SignPath Foundation approves each project separately, so apply for PageVoice early.
- Secrets live only in GitHub repository secrets.

### D22. Where benchmarks run (2026-10-09)
- **Real numbers:** laptop `laptop-tlc3d2rv`.
- **Repeatable baseline:** a GitHub Actions runner, tracked in CI to catch slowdowns.
- **VirtualBox Linux VMs:** packaging and smoke tests only. Use clean Ubuntu 22.04, not Kali, whose libraries are newer than most users have.

### D23. Golden test files are human-owned (2026-10-09)
- Expected text is hand-checked for a few pages per test book.
- Claude can't edit `tests/corpus/**/expected/`, `tests/voice/sentences.tsv` or `src/pagevoice/voice/model_manifest.json`. This is enforced by a PreToolUse hook and permission deny rules. Otherwise the easiest way to make a failing test pass is to change the expected answer.
- Copyrighted books never go in the repo; they stay in git-ignored `tests/corpus/private/`.

### D24. Dev tooling: uv, ruff, pytest, hatchling, Python 3.13 (2026-10-09, chosen during setup)
- uv manages the environment and lockfile.
- ruff formats and lints on every edit (hook).
- pytest runs the tests.
- hatchling is the build backend.
- Python 3.13 is the version already installed on the dev laptop.
The owner confirmed these on 2026-10-09. In M0, check that onnxruntime, PySide6, PyInstaller and the chosen G2P library all have Python 3.13 builds. If one doesn't, drop to 3.12; `requires-python` already allows it.
- **Update 2026-10-16 (M0):** onnxruntime, PySide6 (abi3 wheels), PyInstaller and spaCy all have 3.13 builds, but misaki 0.9.4 declares `requires-python <3.13`. Since misaki is the G2P (D29), the project moved to **Python 3.12** (`.python-version`, `requires-python = ">=3.12,<3.13"`). Revisit when misaki allows 3.13.

### D25. Claude Code setup (2026-10-09)
- A short CLAUDE.md; path-scoped rules in `.claude/rules/`; hooks and permissions in `.claude/settings.json`; project skills for repeated procedures; and a read-only `spec-reviewer` agent run at the end of each milestone.
- No MCP servers (the `gh` command line covers GitHub) and no third-party skill packs (skills can run scripts, so treat them like any dependency we didn't write).
- **Stop hook** (added 2026-10-09): runs the fast tests whenever Claude tries to finish, so it can't call a task done while they fail. On the second attempt it lets the stop through, so it can't loop forever; Claude must then say which tests fail.

### D26. Render cache lives in the user cache directory, with a size cap (2026-10-09)
Kokoro outputs 24 kHz audio, so a 10-hour book's paragraph cache is about 1–2 GB even as FLAC.
- Models, caches and settings go in the per-user directories from platformdirs.
- The cache has a size cap the user can change.
- A book's cache is cleared after a successful export, unless the book is still being edited.

### D27. `main` is protected; everything arrives through pull requests with CI (2026-10-09)
- **No direct pushes to `main`;** no force pushes or deletion. The initial commit was the only direct push.
- **CI** (`.github/workflows/ci.yml`) runs ruff, `pytest -m "not slow"` and the license check on `windows-latest` and `ubuntu-22.04`. Branch protection requires both jobs by name.
- **Releases:** the version bump goes through a `release/vX.Y.Z` branch and PR, and the tag goes on the merge commit.
*Why:* the first commit going straight to `main` was fine, but it should be the last. CI gives branch protection something to require.

### D28. Pause at 90% plan usage; resume on "continue" (2026-10-16)
- Only the status line receives the plan's 5-hour and weekly usage. `usage_statusline.py` saves it to a state file in the temp folder.
- `usage_guard.py` (UserPromptSubmit and PostToolUse) adds a note at 90% and 95%. Claude then commits, updates docs/PROGRESS.md and stops (docs/PAUSE_AND_RESUME.md).
- docs/PROGRESS.md is updated after every finished step, so even a hard stop at 100% loses nothing.
- Claude pushes its branches and merges its own PRs without asking, once CI passes and the spec-reviewer agent finds nothing blocking. Force-pushes, remote branch deletion (`git push --delete`, `gh pr merge --delete-branch`, `gh api -X DELETE`) and refspec tricks (`+ref`, `:ref`) are denied in `.claude/settings.json`. Tags, releases and workflow runs still ask.

*Why:* the owner wants long runs to stop cleanly before the limit and resume with one word, and to finish PRs without waiting on approvals.

### D29. G2P: misaki with espeak-ng fallback (2026-10-16, provisional, closes O1)
- **misaki** (Kokoro's own G2P, Apache-2.0) with spaCy `en_core_web_sm` for part-of-speech tags. Words it doesn't know go to **espeak-ng** (via phonemizer-fork and espeakng-loader, GPL-3.0). Without the fallback, misaki drops unknown names entirely (❓ for "Siobhan", "Nguyen").
- **Heteronyms (`het-*` rows, phoneme output):** misaki 9/12, espeak-ng 9/12. Both miss present-tense "read", "tear" (rip) and "lead" (metal). These go to the pronunciation list for now.
- **Round-trip (faster-whisper small.en, fp32, af_heart, raw text without our normalizer):** misaki 5.3% WER, 14 failing rows; espeak-ng 6.9%, 19 failing rows.
- misaki's transformer tagger (`trf=True`, the `misaki[en]` extra) pulls in PyTorch, so it is off and the extra isn't installed (D3).
- Cost: spaCy + model + espeak-ng add tens of MB to the installer (SPEC O1 expected this), and Python drops to 3.12 (D24).

*Why:* tied on heteronyms, better on the round-trip, and Kokoro was trained on misaki's phoneme set. *Provisional:* the owner hasn't listened yet. *Rejected for now:* espeak-ng alone.

### D30. Model variant: fp32 (2026-10-16, provisional)
Logged in `benchmarks/history.csv`, CPU provider, af_heart, synthesis only:

| Machine | CPU | fp32 × real time | int8 × real time | Peak RAM fp32 / int8 |
|---|---|---|---|---|
| laptop-tlc3d2rv | Ryzen 5 5600H | 2.63 | 2.35 | 1073 / 1037 MB |
| gha-linux | EPYC 7763 | 2.30 | 2.81 | 1138 / 1071 MB |
| gha-windows | EPYC 9V74 | 2.37 | 2.81 | 1080 / 1044 MB |

- A second, unlogged laptop run gave fp32 2.32× and int8 2.22×. Laptop runs vary by about 10%.
- int8 (dynamic quantization) is about 20% faster on the server CPUs but not on the laptop. The laptop is what decides the user experience (D22).
- RAM is about the same either way, and most of it is spaCy plus the runtime. int8's real gain is download size: 92 MB against 326 MB.
- A 10-hour book takes about 4 hours on the laptop either way.

*Why fp32:* faster on the machine that matters, and it's the reference quality. *Provisional:* waiting on the owner's blind A/B listening (`benchmarks/out/2026-10-16-ab/`). If int8 sounds the same, its smaller download and the server-CPU speed may tip it.

### D31. Default voice af_heart, speed 1.0 (2026-10-16, provisional, closes O4)
- af_heart is rated highest in Kokoro's VOICES.md and had the lowest round-trip WER of the voices tried (fp32, misaki, faster-whisper small.en, raw text):

  | Voice | Overall WER |
  |---|---|
  | af_heart | 5.3% |
  | af_bella | 5.4% |
  | am_michael | 6.2% |
  | am_fenrir | 6.2% |
- Speed stays at 1.0 until the owner listens.

*Provisional:* naturalness can't be judged from numbers; the owner picks after listening.

### D32. How M1 reads and cleans books (2026-10-16)
- **Document model** (`src/pagevoice/document.py`): a book is chapters of paragraphs, and a paragraph is a list of spans. A removed span keeps its text, reason and location (page and position, or EPUB file). Restoring it is a flag, so the review screen needs no second copy of the text.
- **PDF extraction uses pdfplumber** (MIT, built on pdfminer.six and pypdfium2), because it gives each word's font size and position. Font size and position are what headers, footnotes and superscript markers are found by. pypdfium2 is only used for bookmarks.
- **Removal reasons beyond the spec:**
  - `contents` (tables of contents)
  - `boilerplate` (Project Gutenberg licence text, publishers' imprint and colophon pages)
  - `hyphen` (a line-break hyphen taken out when a word is rejoined)
  - `multi_column`
  - All are restorable like the others.
- **Multi-column pages** (D14) are flagged, and their text is kept as `multi_column` removals. Column-interleaved text is never read unless the user restores it. Detection looks for a vertical channel of white space that at most one line in ten crosses, with real text on both sides.
- **Paragraph breaks in PDFs** need the previous line to end a sentence, or a blank line between them. The text layers of OCR'd scans shift words and guess font sizes, so indents alone are too noisy.
- **Chapters from text patterns** (D13) need a larger font as well. A scan whose OCR layer gives every line the same size therefore comes out as one chapter, and the user splits it in review.
- **The golden corpus** holds public books by checksum, plus trap PDFs made by `tools/make_trap_pdfs.py`. That script typesets known text, so its candidate pages come from the source text, not from PageVoice's output.

*Why:* nothing is deleted silently (rule 2), and a wrong guess costs the user a click in review, not a garbled audiobook.

---

## Dependency log

Every package added to the project, with its license, checked by `tools/check_licenses.py` (see the `add-dependency` skill).

| Date | Package | License | Group | Why |
|---|---|---|---|---|
| 2026-10-09 | hatchling | MIT | build | Build backend |
| 2026-10-09 | pytest | MIT | dev | Tests |
| 2026-10-09 | ruff | MIT | dev | Format and lint (runs after every edit) |
| 2026-10-09 | pip-licenses | MIT | dev | License check for every installed package |
| 2026-10-16 | onnxruntime | MIT | runtime | Runs Kokoro (D3) |
| 2026-10-16 | numpy | BSD-3-Clause | runtime | Audio arrays, model inputs |
| 2026-10-16 | platformdirs | MIT | runtime | Per-user model, cache and settings folders (D26) |
| 2026-10-16 | misaki 0.9.4 | Apache-2.0 | runtime | G2P (D29); installed without the `[en]` extra, which pulls PyTorch |
| 2026-10-16 | spacy 3.8 | MIT | runtime | Part-of-speech tags for misaki's heteronyms (D29) |
| 2026-10-16 | en-core-web-sm 3.8.0 | MIT | runtime | spaCy's English model, from spaCy's GitHub release (not on PyPI) |
| 2026-10-16 | num2words | LGPL-2.1 | runtime | misaki's number reading |
| 2026-10-16 | phonemizer-fork | GPL-3.0 | runtime | espeak-ng fallback for words misaki doesn't know (D29) |
| 2026-10-16 | espeakng-loader | MIT (bundles espeak-ng, GPL-3.0+) | runtime | Ships the espeak-ng library; metadata empty, so it's in `REVIEWED` |
| 2026-10-16 | psutil | BSD-3-Clause | dev | Peak RAM in the benchmark on Windows |
| 2026-10-16 | faster-whisper | MIT | roundtrip | Transcribes rendered audio for the round-trip check; never shipped. The whole group (94 packages, including av, ctranslate2, tokenizers) passed `check_licenses.py` with `--group roundtrip`; CI checks only the default groups |
| 2026-10-16 | pdfplumber | MIT | runtime | PDF words with font size and position (D5, D32); pulls in pdfminer.six (MIT), pypdfium2 (BSD-3/Apache-2.0), Pillow (MIT-CMU) |
| 2026-10-16 | reportlab | BSD | dev | Typesets the trap PDFs in `tools/make_trap_pdfs.py`; never shipped |
