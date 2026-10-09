---
paths:
  - "src/pagevoice/ingest/**"
  - "src/pagevoice/cleanup/**"
---

# Ingest and cleanup rules

## Never delete silently

Every piece of text that won't be read aloud becomes a **removal**. It keeps the original text, the reason (`header`, `footer`, `page_number`, `footnote`, `footnote_marker`, `caption`, `table`, ...) and where it came from (page and position). The review screen shows it dimmed, and the user can restore it. A rule that drops text without a removal record is a bug.

## Detection rules from the spec

- **Headers and footers:** lines repeating in the top or bottom strip of most pages.
- **Page numbers:** lone numbers in those strips, including Roman numerals in front matter.
- **Footnotes:** smaller text at the bottom of the page. Strip the reference markers from sentences and move the notes to the end of the chapter (a setting drops them). Never read notes inline.
- **Hyphens:** rejoin a word split at a line break only if the joined form appears elsewhere in the book, or the hyphenated form doesn't.
- **Captions and tables:** skipped by default (as removals).
- **Chapters:** top-level PDF bookmarks first. Otherwise font size plus "Chapter N" / "CHAPTER" text patterns together.

## Detect and refuse plainly; don't guess

- **No text layer** means a scanned PDF: tell the user it needs OCR.
- **Multi-column pages** get flagged in review; v1 doesn't reorder columns.

## Known traps to handle

Ligatures (fi, fl), drop caps ("T he"), small caps, soft hyphens, paragraphs spanning pages, and Word-exported PDFs.

## Process

Every change starts from a book where cleanup fails. Use the `add-cleanup-rule` skill, and finish by running the whole golden suite (`uv run pytest tests/corpus`), not just the book you fixed.
