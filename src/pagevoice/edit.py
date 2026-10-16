"""Edits the review screen makes to a book (SPEC §4): restore removed text, and rename,
merge and split chapters. Nothing here deletes text: a merge keeps every paragraph, and a
restore only flips a flag the user can flip back.
"""

from pagevoice.document import Book, Chapter, Span


class EditError(ValueError):
    """An edit that can't be made. The message is plain language."""


def set_restored(span: Span, restored: bool) -> None:
    """Bring a removed span back into the reading, or take it out again."""
    if span.reason is None:
        raise EditError("This text was never removed, so there's nothing to restore.")
    span.restored = restored


def rename_chapter(book: Book, index: int, title: str) -> None:
    title = " ".join(title.split())
    if not title:
        raise EditError("A chapter needs a title.")
    _chapter(book, index).title = title


def merge_with_next(book: Book, index: int) -> None:
    """Join chapter index+1 onto chapter index. The second chapter's heading stays in place
    as a paragraph, so it's still read (and can be removed or restored like any other)."""
    first = _chapter(book, index)
    if index + 1 >= len(book.chapters):
        raise EditError("The last chapter has no next chapter to merge with.")
    second = book.chapters.pop(index + 1)
    first.paragraphs += second.paragraphs
    first.notes += second.notes


def split_at(book: Book, index: int, paragraph: int, title: str | None = None) -> None:
    """Start a new chapter at a paragraph of chapter index. The new chapter's title is the
    given one, or that paragraph's text if it's a heading, or "Chapter N".

    Notes stay with the first part: they're tied to markers that can't be placed reliably."""
    chapter = _chapter(book, index)
    if not 0 < paragraph < len(chapter.paragraphs):
        raise EditError("Split at a paragraph inside the chapter, not at its first one.")
    head = chapter.paragraphs[paragraph]
    if title is None:
        heading = head.text if head.kind == "heading" else ""
        title = heading or f"Chapter {index + 2}"
    new = Chapter(title=" ".join(title.split()), paragraphs=chapter.paragraphs[paragraph:])
    pages = [s.location.page for p in new.paragraphs for s in p.spans if s.location.page]
    new.start_page = pages[0] if pages else None
    chapter.paragraphs = chapter.paragraphs[:paragraph]
    book.chapters.insert(index + 1, new)


def _chapter(book: Book, index: int) -> Chapter:
    if not 0 <= index < len(book.chapters):
        raise EditError(f"There's no chapter {index + 1}.")
    return book.chapters[index]
