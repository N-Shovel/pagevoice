---
name: add-cleanup-rule
description: Add or fix a PDF/EPUB cleanup rule (headers, footers, page numbers, footnotes, hyphens, ligatures, drop caps, captions, chapters). Use whenever extracted text from a real book is wrong. Starts from the failing book, writes the failing golden test first, and ends with the whole golden suite green.
---

# Add a cleanup rule

Work in this order. Don't skip ahead to the fix.

## 1. Start from a real failure

- Name the book (`tests/corpus/<public|private>/<book-id>/`) and the page where cleanup goes wrong.
- Quote the wrong output next to what the printed page says.
- If the book isn't in the corpus yet, add it:
  - **Public domain:** `book.toml` with source URL and SHA-256.
  - **Copyrighted:** copy the file into `tests/corpus/private/`. Never into `public/`.

## 2. Write the failing golden test first

- If `expected/page-NNN.txt` already exists for that page, run `uv run pytest tests/corpus -k <book-id>` and confirm it fails for the reason you described.
- If it doesn't exist:
  1. Write what the page *should* read like into `candidate/page-NNN.txt`, following the format in `tests/corpus/README.md`.
  2. Stop and ask the owner to check it against the printed page and move it into `expected/`. You can't write to `expected/` (the hook blocks it), and that's deliberate.
  3. Continue once it's in place and the test fails.

## 3. Implement the fix

- Put it in `src/pagevoice/cleanup/` (or `ingest/` for extraction problems like ligatures and soft hyphens).
- Follow `.claude/rules/cleanup.md`.
- Make the rule as narrow as the evidence. For example, "repeats on most pages" means a measured fraction, not "appears twice".

## 4. Prove nothing was deleted silently

Add or extend a unit test that asserts each text the rule removes shows up as a removal, with the right reason and page. Those removals are what the review screen shows dimmed.

## 5. Run the whole golden suite

```
uv run pytest tests/corpus
uv run pytest
```

A fix for one book that breaks another isn't done. If another book now fails, either narrow the rule or show the owner both pages and ask which behaviour is right.

## 6. Report

- What the rule does, and the books it fixed.
- The golden pass count before and after.
- Any page where you were unsure.
