# Test corpus

Real books, plus hand-checked text for a few pages of each. Every cleanup change runs against all of them.

```
tests/corpus/
  public/<book-id>/        committed: public-domain books and PDFs we made ourselves
    book.toml              source URL and SHA-256, format, which pages are checked, known traps
    expected/page-NNN.txt  hand-checked text for that page   (PROTECTED: humans only)
    candidate/page-NNN.txt Claude's proposed text, waiting for review
  private/<book-id>/       git-ignored: copyrighted books, same layout plus the book file
  .downloads/              git-ignored: public source files fetched by checksum
```

## How a golden page gets made

1. Claude extracts the page and writes what it should read like into `candidate/page-NNN.txt`.
2. You compare it with the printed page and fix anything wrong.
3. You move it to `expected/page-NNN.txt` yourself.

Claude can't write to `expected/` (blocked by `.claude/hooks/protect_files.py`). Otherwise the easiest way to make a failing test pass would be to change the answer.

## What `expected/` text looks like

- One paragraph per line, in reading order. Paragraphs that run across a page break are joined and belong to the page where they start.
- Headers, footers, page numbers, captions and tables are left out.
- Footnote markers are removed from sentences. The notes themselves go under a line containing only `[notes]`, in order.
- Words hyphenated across a line break are rejoined, and real hyphens are kept ("well-known").
- Ligatures are spelled out (`fi`, not `ﬁ`), soft hyphens are removed and drop caps are joined ("The", not "T he").

## Sources to cover

- **EPUB:** Standard Ebooks and Project Gutenberg.
- **PDF:** Internet Archive scans with a real text layer, plus scholarly books with lots of footnotes.
- **Trap PDFs:** ligatures (fi, fl), drop caps, small caps, soft hyphens, paragraphs that span pages, Word-exported PDFs, a two-column page (must be flagged) and a scanned page with no text layer (must be refused plainly).
