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
  - `figure` (image descriptions, SVG text, MathML and its `alttext`)
  - `non_linear` (EPUB documents outside the reading order; notes cited from them are still moved to their chapter)
  - All are restorable like the others.
- **Multi-column pages** (D14) are flagged, and their text is kept as `multi_column` removals. Column-interleaved text is never read unless the user restores it. Detection looks for a vertical channel of white space that at most one line in ten crosses, with real text on both sides.
- **Paragraph breaks in PDFs** need the previous line to end a sentence, or a blank line between them. The text layers of OCR'd scans shift words and guess font sizes, so indents alone are too noisy.
- **Chapters from text patterns** (D13) need a larger font as well. A scan whose OCR layer gives every line the same size therefore comes out as one chapter, and the user splits it in review.
- **The golden corpus** holds public books by checksum, plus trap PDFs made by `tools/make_trap_pdfs.py`. That script typesets known text, so its candidate pages come from the source text, not from PageVoice's output.

- **Language:** each file's own language (`dc:language`, the PDF's `/Lang`, Gutenberg's `Language:` field) is carried into `Book.language`, normalised (`eng`/`English` → `en`). A non-English book is refused with a plain message, and the caller can override a wrong label.
- **Copy-protected PDFs (provisional):** a PDF that opens with an empty password but forbids copying text is refused, with the same message as a password-protected one. Restrictions on printing alone are fine. The owner may decide this is too strict.

*Why:* nothing is deleted silently (rule 2), and a wrong guess costs the user a click in review, not a garbled audiobook.

### D33. How M2 turns text into audio (2026-10-16)
- **Order:**
  1. Pronunciation entries are swapped in as placeholders.
  2. The text is normalized for the book's language (`normalize/en.py`).
  3. The placeholders are filled with the respelling or misaki's `[word](/phonemes/)` markup.
  4. G2P, then Kokoro.
  - This way a case-sensitive entry ("NASA") matches before normalization changes the word's case, and normalization never touches a respelling.
  - Placeholders look like an ordinary word with the replaced word's capital, so "Dr. Jones" and "Henry VIII" keep their context when the name is in a list.
  - Whole-word entries still match before "'s", "'ll" and inside quotes, but not after "O'" ("O'Brien").
  - Per-book entries win over global ones wherever both match, even when their case settings differ.
  - **Respellings are lowercased before the G2P** (provisional). misaki spells a capital syllable as letters ("DAR-see" became "D A R see") and ignores capitals for stress. Stress that matters goes in the phonemes column.
- **Normalization is narrow on purpose.** Ambiguous patterns are left as printed. All 59 rows of `tests/voice/sentences.tsv` match word for word. misaki only ever sees words, so its own number reading never runs.
- **Ambiguous abbreviations:**
  - "Dr." and "St." mean Doctor or Saint before a name, and Drive or Street after a capitalised word or a number.
  - A Roman numeral is read as a cardinal after words like Chapter, War or Part, and as "the Eighth" after a name ("Henry VIII"). A lone "I" is never converted after a name, nor after a lowercase keyword when a word follows ("the letter I sent").
  - All-capital words are read as words, except a short list of initialisms and vowel-less words, which are spelled out. "US" is spelled out unless the line is in capitals.
- **Years:** a 4-digit number (1100–2099) is read as a year only with context: a cue word before it (in, by, since, of, a month...), a year before "and"/"to", the start of a sentence, the end of a clause, or an era. Otherwise it's a count ("had 1500 soldiers"). Dates like 12/25/1990 are read number by number, never as fractions.
- **Render cache:**
  - One FLAC file per paragraph, via soundfile (BSD-3-Clause, bundles libsndfile LGPL-2.1).
  - The file is named by a SHA-256 of the normalized text, the matched entries, voice, variant, model and voice checksums, speed, G2P backend and its package versions, language and a cache version. Notes on pronunciation entries aren't part of it.
  - Writes are atomic, with unique temp names; temp files left by a crash are removed after an hour. Audio is clipped before 16-bit FLAC. The default cap is 5 GB, with least-recently-used eviction that never evicts the current book's paragraphs.
  - Each book's key index (added to, never overwritten) lets its cache be cleared after export (D26).
- **Rendering:**
  - One failing paragraph is logged and skipped; it doesn't stop the book.
  - The voice reads in the book's language (en-GB gets British G2P). Text the G2P can't pronounce is reported per paragraph.
  - The ETA comes from characters per second measured in the current run.
  - Pauses: 0.45 s between paragraphs, 1 s after headings and 1.5 s at chapter end. These are provisional until the owner listens.

*Why:* the cache is what makes crash-resume and one-paragraph fixes cheap (D16), so anything that changes the audio has to change the key.

### D34. How M3 writes audiobooks (2026-10-16)
- **ffmpeg** (D18):
  - Built by `packaging/ffmpeg/build.sh` from pinned, checksummed sources: ffmpeg 8.1.3 and LAME 3.100.
  - Configured with `--disable-everything --disable-autodetect`, then only the parts the exporters use, plus zlib (zlib licence; the PNG decoder needs it) and the platform's threads.
  - The script refuses to ship a binary that reports GPL or nonfree, or that lacks a decoder, encoder or muxer the exporters use. configure only warns when it drops one; that's how a PNG cover first failed in CI.
  - Linux links zlib dynamically (it's on every system). Windows links everything statically.
  - The app looks in its own bundle, then in `packaging/ffmpeg/out/` (development), never on PATH. `PAGEVOICE_FFMPEG` works in development only, never in the installed app.
- **How audio gets to ffmpeg:**
  - Each chapter is written from the render cache as one FLAC, in a work folder inside the cache directory, not the system temp folder (about 1 GB for 10 hours; `/tmp` can be RAM).
  - Chapter times come from those files' exact lengths, rounded to the millisecond, back to back.
- **M4B:**
  - Written with ffmpeg's ipod muxer as 64 kbps mono AAC (D17).
  - Chapters are written both as a QuickTime chapter track (Apple) and as Nero `chpl` (most other players); tests check both.
  - Tags: title, album, artist, album artist, genre "Audiobook", the iTunes audiobook media type, a "Made with PageVoice" comment, and the audio language (ISO 639-2, "eng").
- **MP3:**
  - One file per chapter, named `NNN - Title.mp3`. The title has characters Windows forbids removed and is cut at 80 characters, so the files sort in order everywhere.
  - Encoded as 64 kbps mono, the same as the M4B.
  - ID3v2.3 tags: title, album, artist, track `n/total`, genre and language.
  - After a full export, earlier `NNN - *.mp3` files in that folder that weren't rewritten are removed. Nothing else in the folder is touched.
  - If cancelled, the chapters already finished are kept, and the CLI says so.
- **Covers:** JPEG and PNG are embedded as attached pictures. Other types (GIF, WebP, SVG) are left out with a plain warning. Converting them is a possible later improvement.
- **Safety:**
  - Output is written to `.part` and renamed when complete.
  - On cancel, Ctrl+C or a failing progress callback, ffmpeg is stopped before the partial file is deleted.
  - Both exporters check for ffmpeg before preparing any audio.
- **Cache after export (D26):** the exporters clear the book's render cache only when asked (`clear_cache`). The CLI clears it by default, and `--keep-cache` keeps it. The GUI (M4) keeps it while the book is still being edited.

### D35. How the M4 desktop app works (2026-10-16)
- **Flow:** Open → Review → Voice and export. PDFs open in review; EPUB and TXT go straight to voice and export, and review is one click away (SPEC §4).
- **Saved review** (`pagevoice/project.py`):
  - What's saved: the whole cleaned book as JSON in the per-user data folder, including every span with its reason, location and restored flag, and chapter edits.
  - It's keyed by a hash of the source file, so a changed file starts fresh. It's saved in the background after edits and comes back when the same file is reopened, which keeps the render cache keys valid. The CLI uses it too.
  - A saved review that can't be read is kept as `.bak`, and the user is told.
  - Per-book pronunciation lists sit next to it.
- **Chapter edits** (`pagevoice/edit.py`):
  - A merge remembers the second chapter's title and start page, so splitting at the same place restores them.
  - Otherwise a split takes the heading's text or asks for a title. The engine never makes up titles, because that would be English text outside a language module.
- **Threads** (`pagevoice_gui/tasks.py`):
  - Slow work runs as tasks on Qt's thread pool (QThreadPool threads are QThreads). Results come back as queued signals to a relay object on the UI thread.
  - Covered: opening, cleaning, hashing, checking the voice files, planning, rendering, exporting, downloading, previews, saving, measuring the cache.
  - The book is guarded by a lock that review edits and saves share. Review edits are locked while a render or export runs.
  - **Provisional:** the GUI rule says "QThread or a worker object moved to one"; this is the same mechanism through the pool. The owner should confirm, and the rule's wording should be updated to match.
- **Big books:** review shows long chapters in parts of 200 paragraphs. A restore click restyles only the clicked text, and only the edited chapter's word count is recomputed.
- **Voice:**
  - One `VoiceSetup` per voice is shared by rendering and previews. Its checksum is checked once per run, and G2P and synthesis take turns under a lock.
  - DirectML is offered only when the installed onnxruntime has it.
- **First-run download:** it counts as busy work, in a modal dialog with cancel. Afterwards it continues whatever asked for it.
  - It always comes from our release, verified against the manifest. The upstream source is only for a development run (`--dev-proposed-manifest`, never in a frozen build).
  - A damaged download gets a plain message.
- **Cache:**
  - The size cap is a setting (File → Settings, default 5 GB), which also shows the size in use and can empty the cache.
  - After an export the book's audio is kept, and a "Free this book's rendered audio" button appears.
- **Language:** a book labelled as another language can be read as English after asking (D32). The book's language is shown on the voice page.
- **Preview playback:** PySide6-Essentials has no QtMultimedia, so previews play with `winsound` on Windows, and `pw-play`, `paplay` or `aplay` on Linux.
- **Errors:** never shown as a traceback. They're logged to the per-user log folder and shown as a short message.

### D36. Listen: play rendered chapters in the app (2026-10-19)
- **The owner's call:** PageVoice stays an audiobook maker, not a reader. But you can hear the result before exporting, so a wrong name or pause is caught without an export and an outside player.
- **Engine** (`render/playback.py`, no Qt):
  - A chapter is a timeline of cached paragraphs plus their pauses. Lengths come from the FLAC headers, so no audio is loaded to build it.
  - `ChapterPlayer` writes it to the sound card in 0.1 s blocks on its own thread, so pause, seek and stop act within about 0.1 s.
  - A paragraph that isn't rendered is waited for while a render runs; otherwise playback ends there and says so.
- **GUI:** a Listen bar under every step once a book is open: chapter, play/pause, stop, a seek slider, the time, and the paragraph being read. Review's right-click adds "Listen from here".
  - It plays from the same render plan as Render and Export; nothing is rendered for it.
  - It works during a render, and stops when the book's audio is freed, the book is cleaned again, or the app quits.
- **Playback library:** sounddevice (MIT, PortAudio), in the `gui` extra.
  - *Rejected:* QtMultimedia, because PySide6-Addons would make the install much bigger; and opening the chapter in the system player, because it can't jump to a paragraph or show the text.
  - Linux needs libportaudio2; without it, listening says plainly that sound can't be played.
  - M5 must leave the ASIO builds of PortAudio (`*-asio.dll`) out of the Windows package (Steinberg licence).

### D37. Cleanup and reading fixes from the external review (2026-10-19)
Every rule that fired on one clue now needs a second clue, or evidence from elsewhere in the book.
- **Numbered running heads** ("12 THE WISDOM OF LIFE"): the shape must top at least 30% of pages (and 3). Their Roman numeral is all lower or all upper case and not a lone "I", so "I never saw him…" or "Vic …" at the top of a page stay.
- **Drop caps:** a capital that is a word on its own (English: A, I; in `cleanup/en.py`) keeps its space when the next word occurs elsewhere in the book: "I was", "A long". "T he" and "I t" still join.
- **Captions:** "Table 2 shows that…" is a sentence, not a caption. After the number, a caption has punctuation, a capital or nothing.
- **Bookmarks** that point partway down a page start their chapter, and its footnotes, there (XYZ/FitH positions). Whole-page bookmarks work as before.
- **EPUB:** `<a href="#fn"><sup>1</sup></a>` is a note marker like `<sup><a>`. SVG `<title>` text is a figure removal.
- **PDF extraction:** text drawn twice ("fake bold") is read once, and pages are closed as they're read.
- **Reading:**
  - A Roman numeral reads as "the Nth" after a name only up to 30, so DC, MD, MI, CD and XL stay letters. No numeral is read before a hyphen ("mix-up").
  - A fraction needs a smaller top and a usual denominator, so "9/11", "24/7" and "50/50" read as two numbers.
  - "etc.", "a.m.", "p.m.", "A.D." and "B.C." keep their full stop before a new sentence. "Baker St. The" is Street.
  - With a cue word, any year 1000-2999 is a year ("in 1066", "in 2312").
  - Proposed rows for `sentences.tsv` are in `tests/voice/sentences.proposed.tsv`, waiting for the owner.
- **Project Gutenberg markers** are PG's file format, not English rules, so they live in `cleanup/gutenberg.py`.
- **Checked against the corpus:** removal counts before and after on all 10 corpus books. Two lines changed:
  - Wisdom of Life's "X SCHOPENHAUER" head stays removed.
  - Essays of Elia's 8 garbled OCR heads are now labelled multi-column; those pages aren't read either way.

  The golden pages still wait for the owner, so these rules are only covered by unit tests.

### D38. How releases are built (M5, 2026-10-22)
- **App:** PyInstaller in one-folder mode (`packaging/pagevoice.spec`, never one-file).
  - Bundled: spaCy and its English model, misaki, espeak-ng, ONNX Runtime, Qt, PortAudio and libsndfile, the LGPL ffmpeg, the icon, `LICENSE` and `THIRD_PARTY_LICENSES.txt`.
  - Left out: PortAudio's ASIO builds (Steinberg licence, D36), other platforms' libraries, unused Qt modules, and every test, build and round-trip tool.
  - The voice model is never bundled. It's downloaded on first run from our release (D9).
  - About 440 MB unpacked on Windows.
- **Self-test:** `PageVoice --self-test REPORT` checks, in the built app itself:
  - normalization; the G2P on dictionary words (misaki, spaCy) and on unknown names (espeak-ng); ONNX Runtime; FLAC
  - the bundled ffmpeg, by encoding a real M4B (AAC, ipod) and MP3 (LAME)
  - the sound library, the PDF and EPUB readers, and Qt
  - the voice manifest

  CI runs it on both builds, on the AppImage (under a real X display, with the system PortAudio removed) and again after signing. It already caught one real gap: `language_tags` data missing, which would have broken every render.

  The manifest check may fail until the owner publishes the real voice manifest, but never in a version-tag build (`PAGEVOICE_RELEASE=1`): an installer that can't download its voice is never released.
- **Developer manifest:** the installed (frozen) app never uses the proposed manifest or the upstream download, whatever the caller asks (guards in `voice/manifest.py` and `voice/download.py`), and the proposed manifest isn't bundled.
- **Windows:** an Inno Setup installer (`packaging/windows/pagevoice.iss`), compiled with Inno Setup 6.7.1, pinned.
  - Per-user by default, with no administrator prompt; "all users" is offered.
  - Start-menu entry, optional desktop icon, uninstaller.
  - An upgrade replaces `_internal` completely.
  - The user's voice, cache, reviews and lists are never removed.
  - The launcher shows no error dialog (`disable_windowed_traceback`), so a broken build can't hang CI.
- **Linux:** an AppImage built on ubuntu-22.04 (`packaging/linux/build-appimage.sh`).
  - Qt's X11 (xcb) libraries are installed before building, so PyInstaller bundles them.
  - appimagetool 1.9.1 and the type2 runtime 20251108 are pinned by SHA-256.
- **Release workflow** (`.github/workflows/release.yml`), mirroring folder-tracker:
  - A `v*` tag builds ffmpeg (through the ffmpeg workflow), the Windows and Linux apps and the sources, and all three jobs attach to one release, handling the create race.
  - Pull requests that touch packaging build and self-test without releasing.
  - Jobs and self-tests have timeouts. The tag and version reach scripts only through `env:`.
- **Signing:** SignPath signs the app folder, then the installer.
  - Only for version tags, and only when both `SIGNPATH_API_TOKEN` and `SIGNPATH_ORGANIZATION_ID` exist. Pull requests and manual builds are never signed.
  - The owner sets up project `pagevoice`, policy `release-signing`, and artifact configurations `app-folder` and `installer`. Until then, releases are unsigned.
  - Still to do once SignPath exists: sign Inno Setup's uninstaller (`SignTool=` with `SignedUninstaller=yes`).
- **Sources and licences** for the copyleft software in the builds:
  - **Attached to every release:**
    - ffmpeg 8.1.3, LAME 3.100, espeak-ng 1.52.0 (espeakng-loader builds it unmodified from that tag) and libsndfile 1.2.2, pinned by SHA-256 (`packaging/sources.sh`)
    - the source archives of every bundled GPL/LGPL/MPL Python package, taken from `uv.lock` and checked against its SHA-256 (`tools/third_party.py --sources`)
  - **Linked, not attached:** Qt 6.12.0 and PySide6/shiboken6 6.12.0 have no source archive on PyPI, and Qt's is about 1 GB. `SOURCES.txt` links their exact-version source on Qt's official servers, which LGPL-3.0 allows with clear directions. The owner may prefer to attach them; it's one more fetch line.
  - **`THIRD_PARTY_LICENSES.txt`** (bundled and attached): the runtime packages with their licence texts, the native libraries with exact versions, and the full GPL, LGPL-2.1, LGPL-3.0 and MPL-2.0 texts (vendored in `packaging/licenses/`).
- **Icon:** a simple placeholder drawn in code (`packaging/icons/`): an open book with sound waves. The owner may replace it.

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
| 2026-10-16 | soundfile | BSD-3-Clause (bundles libsndfile, LGPL-2.1) | runtime | FLAC paragraph cache (D33) |
| 2026-10-16 | mutagen | GPL-2.0-or-later | dev | Reads back M4B chapters and tags and MP3 ID3 tags in `tests/test_export.py`; the bundled ffmpeg has no ffprobe or AAC/MP3 decoders. Never shipped |
| 2026-10-16 | PySide6-Essentials 6.12 | LGPL-3.0 (or GPL-2.0/3.0) | gui extra | The desktop app (D2). The Essentials subset (QtCore, QtGui, QtWidgets) without the add-on modules; pulls in shiboken6 (same licence). About 209 MB installed; the M5 build keeps only the Qt libraries used |
| 2026-10-19 | sounddevice 0.5 | MIT (pulls cffi MIT-0, pycparser BSD-3-Clause; bundles PortAudio, MIT-style) | gui extra | Playing rendered chapters in the app (D36). The wheel also carries ASIO builds of PortAudio (`*-asio.dll`): ASIO is under Steinberg's own licence, so M5 must leave those files out of the build. Linux uses the system's libportaudio2 |
| 2026-10-22 | pyinstaller 6.22 (+ pyinstaller-hooks-contrib) | GPL-2.0-or-later with the bootloader exception (hooks: GPL-2.0-or-later or Apache-2.0) | build | Makes the one-folder app (SPEC §9). Metadata says only "GPLv2", so both are in `REVIEWED` after checking COPYING.txt; the bootloader exception allows shipping its launcher inside PageVoice |
| 2026-10-22 | regex (via misaki, phonemizer-fork) | Apache-2.0 AND CNRI-Python | runtime | Already installed since M0; the stricter AND rule now checks every part, so it's in `REVIEWED`: CNRI-Python is the Python 1.6.1 licence, GPL-compatible |
