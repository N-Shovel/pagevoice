---
paths:
  - "src/pagevoice/**"
---

# Engine rules

- **No Qt, and no import of `pagevoice_gui`.** `tests/test_architecture.py` enforces this.
- **Report progress through callbacks or iterators, never `print`.** Use `logging` for diagnostics. Only `cli.py` writes to stdout.
- **No network access** except the first-run model download in `voice/`, which verifies the SHA-256 from `model_manifest.json` before using the file. Everything else works offline.
- **Language-aware:** every book carries a language code. Text rules (numbers, abbreviations, Roman numerals) live in one module per language, e.g. `normalize/en.py`. Nothing outside those modules assumes English.
- **Paths:** use `pathlib` and open text files as UTF-8 explicitly. The code must behave the same on Windows and Linux.
- **Long jobs are resumable:** rendering writes each paragraph to the cache atomically (write to a temp file, then rename), so a crash never leaves a half-written entry that looks valid.
- **Dependencies:** anything new goes through the `add-dependency` skill. PyMuPDF, EbookLib and PyTorch are banned (ruff TID251 blocks them).
