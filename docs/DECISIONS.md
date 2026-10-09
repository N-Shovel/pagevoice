# Decisions

Why PageVoice is built the way it is. These are settled. Don't re-argue them in a new session. To change one, ask the project owner, then edit the entry and add a dated note saying what changed and why.

Format: **decision**, then *why*, then the alternatives that were rejected.

---

### D1. License: GPL-3.0 (decided 2026-10-09)
Most Kokoro setups use espeak-ng to turn text into phonemes, and espeak-ng is GPL, as is Piper now. Licensing the app GPL avoids the conflict. SignPath Foundation only signs open-source projects, so this also gets free code signing.
*Rejected:* a closed or commercial version later. It would mean replacing the GPL parts and losing free signing, so it is ruled out now.

### D2. Python + PySide6 (2026-10-09)
The engine is Python anyway, so the GUI is too.
*Rejected:* Tauri and Electron. We'd still ship Python alongside them, so we'd maintain two runtimes just for a nicer settings screen.

### D3. ONNX Runtime, never PyTorch (2026-10-09)
PyTorch makes the installer gigabytes. Ruff bans `import torch`. An optional GPU speed-up on Windows goes through DirectML, which covers NVIDIA, AMD and Intel.

### D4. Engine and GUI are separate packages (2026-10-09)
`pagevoice` (engine and small CLI) never imports Qt. `pagevoice_gui` is just one way to drive it. This is enforced by `tests/test_architecture.py`.

### D5. No AGPL libraries: no PyMuPDF, no EbookLib (2026-10-09)
Both are AGPL. Use pypdfium2 or pdfplumber for PDFs. Parse EPUB ourselves, since it's just a zip of XHTML files plus an OPF manifest. Ruff bans `fitz`, `pymupdf` and `ebooklib`, and `tools/check_licenses.py` fails on any AGPL, non-commercial or unknown license.

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
*Open to change:* the owner didn't specify these; they are conventional defaults.

### D25. Claude Code setup (2026-10-09)
- A short CLAUDE.md; path-scoped rules in `.claude/rules/`; hooks and permissions in `.claude/settings.json`; project skills for repeated procedures; and a read-only `spec-reviewer` agent run at the end of each milestone.
- No MCP servers (the `gh` command line covers GitHub) and no third-party skill packs (skills can run scripts, so treat them like any dependency we didn't write).

---

## Dependency log

Every package added to the project, with its license, checked by `tools/check_licenses.py` (see the `add-dependency` skill).

| Date | Package | License | Group | Why |
|---|---|---|---|---|
| 2026-10-09 | hatchling | MIT | build | Build backend |
| 2026-10-09 | pytest | MIT | dev | Tests |
| 2026-10-09 | ruff | MIT | dev | Format and lint (runs after every edit) |
| 2026-10-09 | pip-licenses | MIT | dev | License check for every installed package |
