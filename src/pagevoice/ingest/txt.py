"""Plain-text books: paragraphs split by blank lines, chapters found by heading lines."""

import re
from pathlib import Path

from pagevoice.cleanup.language import rules_for
from pagevoice.cleanup.text import fix_characters, join_lines, word_counts
from pagevoice.document import Book, Chapter, Location, Paragraph, Reason, Span

_BLANK = re.compile(r"\n[ \t]*\n")
# Project Gutenberg marks italics as _word_; the underscores aren't text.
_MARKER = re.compile(r"^(\[Illustrations?:?\s*|)(.*?)(\]?)$", re.S)
_EMPHASIS = re.compile(r"(?<![\w_])_([^_\n][^_]*?)_(?![\w_])")


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 with BOM, else Windows-1252."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_txt(path: Path, *, language: str = "en") -> Book:
    rules = rules_for(language)
    text = fix_characters(decode(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n"))
    blocks = [b for b in _BLANK.split(text) if b.strip()]

    fields = dict(rules.GUTENBERG_FIELD.findall(text[:5000]))
    book = Book(
        title=fields.get("Title", path.stem).strip(),
        author=fields.get("Author", "").strip(),
        language=language,
        source_format="txt",
    )

    # Project Gutenberg licence text: kept, but as removals.
    start = next((i for i, b in enumerate(blocks) if rules.GUTENBERG_START.search(b)), None)
    end = next((i for i, b in enumerate(blocks) if rules.GUTENBERG_END.search(b)), None)

    counts = word_counts(blocks)
    front: list[Paragraph] = []
    chapters: list[Chapter] = []
    current: Chapter | None = None
    in_illustration = False
    for index, block in enumerate(blocks):
        location = Location(top=float(index))
        boilerplate = (start is not None and index <= start) or (end is not None and index >= end)
        if boilerplate:
            paragraph = Paragraph.removed(block.strip(), Reason.BOILERPLATE, location)
            (current.paragraphs if current else front).append(paragraph)
            continue
        if in_illustration or rules.ILLUSTRATION_START.match(block):
            # A picture marker runs until the block that closes its bracket.
            if in_illustration:
                in_illustration = "]" not in block
            else:
                in_illustration = block.count("[") > block.count("]")
            # Illustrated chapter openings put the heading inside the marker:
            # "[Illustration:" ... "Chapter I.]". The heading still starts a chapter.
            marker = _MARKER.match(block.strip())
            inner = marker.group(2).strip() if marker else ""
            if inner and rules.is_chapter_heading(inner):
                spans = [
                    Span(marker.group(1), Reason.CAPTION, location),
                    Span(inner, None, location),
                ]
                if marker.group(3):
                    spans.append(Span(marker.group(3), Reason.CAPTION, location))
                current = Chapter(title=inner)
                current.paragraphs.append(Paragraph(spans, kind="heading"))
                chapters.append(current)
                continue
            paragraph = Paragraph.removed(block.strip(), Reason.CAPTION, location)
            (current.paragraphs if current else front).append(paragraph)
            continue
        block = _EMPHASIS.sub(r"\1", block)
        lines = [(line, location) for line in block.split("\n")]
        single = " ".join(line.strip() for line in block.split("\n")).strip()
        if rules.is_chapter_heading(single):
            current = Chapter(title=single)
            current.paragraphs.append(Paragraph.plain(single, location, kind="heading"))
            chapters.append(current)
            continue
        paragraph = Paragraph(join_lines(lines, counts))
        (current.paragraphs if current else front).append(paragraph)

    book.chapters = finish_chapters(chapters, front, book.title, rules)
    return book


def finish_chapters(
    chapters: list[Chapter], front: list[Paragraph], title: str, rules
) -> list[Chapter]:
    """Tidy heading-only chapters and put text before the first heading in front matter.

    A run of three or more heading-only chapters is a table of contents: it joins the
    front matter. A lone heading-only chapter ("BOOK II" before "CHAPTER I") is folded
    into the chapter after it.
    """
    out: list[Chapter] = []
    run: list[Chapter] = []

    def flush_run(next_chapter: Chapter | None) -> None:
        if len(run) >= 3 or next_chapter is None:
            target = out[-1].paragraphs if out else front
            for empty in run:
                target.extend(empty.paragraphs)
        elif next_chapter is not None:
            heads = [p for empty in run for p in empty.paragraphs]
            next_chapter.paragraphs[:0] = heads
            next_chapter.title = " ".join([*(e.title for e in run), next_chapter.title])
        run.clear()

    for chapter in chapters:
        if all(p.kind == "heading" for p in chapter.paragraphs):
            run.append(chapter)
            continue
        flush_run(chapter)
        out.append(chapter)
    flush_run(None)

    if not out:
        return [Chapter(title=title, paragraphs=front)]
    if any(p.text for p in front):
        out.insert(0, Chapter(title=rules.FRONT_MATTER_TITLE, paragraphs=front))
    elif front:
        out[0].paragraphs[:0] = front  # only removals (e.g. boilerplate): keep them
    return out
