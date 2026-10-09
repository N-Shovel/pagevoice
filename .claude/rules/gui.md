---
paths:
  - "src/pagevoice_gui/**"
---

# GUI rules (PySide6)

- **Never block the UI thread.** Extraction, cleanup, rendering, export, model download and file hashing all run off the UI thread, in a `QThread` or a worker object moved to one. Results come back through signals. If a call could take more than about 50 ms on a slow laptop, it goes to a worker.
- **Talk to the engine through its public API only.** No cleanup, normalization or audio logic lives in the GUI. If the GUI needs something, add it to the engine and test it there.
- **Progress, pause and cancel are first-class.** Long jobs report progress the engine computes (paragraphs done, estimated time left from the measured speed). The user can pause, cancel and resume after a restart.
- **Review screen:** removed text is shown dimmed with its reason (header, page number, footnote, caption, table) and can be restored. Scanned pages and multi-column pages are flagged plainly.
- **Plain language in the UI.** Say "This PDF is a scan with no text, so PageVoice can't read it. Run it through OCR first." Never show a traceback to the user. Log it and show a short message.
- **Strings** go through `self.tr()` so translation is possible later, even though v1 is English-only.
