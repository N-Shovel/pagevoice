"""Plain-text books: paragraphs split by blank lines, chapters found by heading lines."""

import re
from pathlib import Path

from pagevoice.cleanup import en as gutenberg  # PG's own header and licence are English
from pagevoice.cleanup.chapters import finish_chapters
from pagevoice.cleanup.language import book_language, rules_for
from pagevoice.cleanup.text import fix_characters, join_lines, split_markers, word_counts
from pagevoice.document import Book, Chapter, Location, Paragraph, Reason, Span
from pagevoice.textfile import decode

_BLANK = re.compile(r"\n[ \t]*\n")
# Project Gutenberg marks italics as _word_; the underscores aren't text.
_EMPHASIS = re.compile(r"(?<![\w_])_([^_\n][^_]*?)_(?![\w_])")
MAX_MARKER_BLOCKS = 6  # an unclosed "[Illustration" or "[Footnote" stops after this many


def read_txt(path: Path, *, language: str | None = None) -> Book:
    text = fix_characters(decode(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n"))
    fields = dict(gutenberg.GUTENBERG_FIELD.findall(text[:5000]))
    book = Book(
        title=fields.get("Title", path.stem).strip(),
        author=fields.get("Author", "").strip(),
        language=book_language(fields.get("Language"), language),
        source_format="txt",
    )
    rules = rules_for(book.language)
    blocks = [b for b in _BLANK.split(text) if b.strip()]

    # Project Gutenberg licence text: kept, but as removals.
    start = next((i for i, b in enumerate(blocks) if gutenberg.GUTENBERG_START.search(b)), None)
    end = next((i for i, b in enumerate(blocks) if gutenberg.GUTENBERG_END.search(b)), None)
    has_notes = any(rules.FOOTNOTE_BLOCK.match(b) for b in blocks)

    counts = word_counts(blocks)
    front: list[Paragraph] = []
    chapters: list[Chapter] = []
    current: Chapter | None = None
    marker: str | None = None  # inside a multi-block "[Illustration" or "[Footnote"
    marker_blocks = 0
    note: Paragraph | None = None
    early_notes: list[Paragraph] = []  # notes before the first chapter heading

    def add(paragraph: Paragraph) -> None:
        (current.paragraphs if current else front).append(paragraph)

    for index, block in enumerate(blocks):
        location = Location(block=index)
        stripped = block.strip()
        boilerplate = (start is not None and index <= start) or (end is not None and index >= end)
        if boilerplate:
            add(Paragraph.removed(stripped, Reason.BOILERPLATE, location))
            continue

        # A marker that never closes ends at a chapter heading or after a few blocks. The
        # block that closes it ("Chapter I.]") still belongs to it.
        closes = "]" in block
        too_long = marker_blocks >= MAX_MARKER_BLOCKS
        if marker and not closes and (too_long or rules.is_chapter_heading(_one_line(block))):
            marker = None
        if marker == "note" or (marker is None and rules.FOOTNOTE_BLOCK.match(block)):
            marker, marker_blocks = _bracket_state(marker, block, "note", marker_blocks)
            continuing = marker_blocks > 1 and note is not None
            note = _note(block, location, rules, note if continuing else None)
            if not continuing:
                (current.notes if current else early_notes).append(note)
            continue
        if marker == "illustration" or (marker is None and rules.ILLUSTRATION_START.match(block)):
            marker, marker_blocks = _bracket_state(marker, block, "illustration", marker_blocks)
            # Illustrated chapter openings put the heading inside the marker:
            # "[Illustration:" ... "Chapter I.]". The heading still starts a chapter.
            parts = rules.ILLUSTRATION_PARTS.match(stripped)
            inner = parts.group(2).strip() if parts else ""
            if inner and rules.is_chapter_heading(inner):
                spans = [
                    Span(parts.group(1), Reason.CAPTION, location),
                    Span(inner, None, location),
                ]
                if parts.group(3):
                    spans.append(Span(parts.group(3), Reason.CAPTION, location))
                current = Chapter(title=inner)
                current.paragraphs.append(Paragraph(spans, kind="heading"))
                chapters.append(current)
                marker = None
                continue
            add(Paragraph.removed(stripped, Reason.CAPTION, location))
            continue
        if rules.CONTENTS.match(block):
            add(Paragraph.removed(stripped, Reason.CONTENTS, location))
            continue
        block = _EMPHASIS.sub(r"\1", block)
        single = _one_line(block)
        if rules.is_chapter_heading(single):
            current = Chapter(title=single)
            current.paragraphs.append(Paragraph.plain(single, location, kind="heading"))
            chapters.append(current)
            continue
        spans = join_lines([(line, location) for line in block.split("\n")], counts)
        if has_notes:
            spans = split_markers(spans, rules.FOOTNOTE_REF)
        add(Paragraph(spans))

    book.chapters = finish_chapters(chapters, front, book.title, rules)
    book.chapters[0].notes[:0] = early_notes
    return book


def _one_line(block: str) -> str:
    return " ".join(line.strip() for line in block.split("\n")).strip()


def _bracket_state(marker: str | None, block: str, kind: str, count: int) -> tuple:
    """Track a bracketed marker that may run over several blocks."""
    if marker is None:
        still_open = block.count("[") > block.count("]")
        return (kind if still_open else None), 1
    return (kind if "]" not in block else None), count + 1


def _note(block, location, rules, note):
    """A "[Footnote 1: text]" block as a note paragraph; a continuation block extends note."""
    text = block.strip()
    if note is not None:
        body = text[:-1] if text.endswith("]") else text
        note.spans.append(Span(" " + _one_line(body), location=location))
        if text.endswith("]"):
            note.spans.append(Span("]", Reason.FOOTNOTE_MARKER, location))
        return note
    head = rules.FOOTNOTE_BLOCK.match(text)
    prefix = text[: head.end()] if head else ""
    body = text[len(prefix) :]
    spans = [Span(prefix, Reason.FOOTNOTE_MARKER, location)] if prefix else []
    closing = body.endswith("]")
    spans.append(Span(_one_line(body[:-1] if closing else body), location=location))
    if closing:
        spans.append(Span("]", Reason.FOOTNOTE_MARKER, location))
    return Paragraph(spans, kind="note")
