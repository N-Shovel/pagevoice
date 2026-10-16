"""Edits the review screen makes to a book (SPEC §4): restore removed text, and rename,
merge and split chapters. Nothing here deletes text: a merge keeps every paragraph, and a
restore only flips a flag the user can flip back.
"""

from pagevoice.document import Book, Chapter, MergedTitle, Span


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
    offset = len(first.paragraphs)
    first.merged.append(MergedTitle(offset, second.title, second.start_page))
    first.merged += [
        MergedTitle(m.paragraph + offset, m.title, m.start_page) for m in second.merged
    ]
    first.paragraphs += second.paragraphs
    first.notes += second.notes


def split_at(book: Book, index: int, paragraph: int, title: str | None = None) -> None:
    """Start a new chapter at a paragraph of chapter index. Its title is the given one, else
    the title it had before a merge, else that paragraph's text if it's a heading. With none
    of those, EditError asks for one: the engine doesn't invent titles in any language.

    Notes stay with the first part: they're tied to markers that can't be placed reliably."""
    chapter = _chapter(book, index)
    if not 0 < paragraph < len(chapter.paragraphs):
        raise EditError("Split at a paragraph inside the chapter, not at its first one.")
    before = next((m for m in chapter.merged if m.paragraph == paragraph), None)
    head = chapter.paragraphs[paragraph]
    if title is None:
        title = before.title if before else (head.text if head.kind == "heading" else "")
    title = " ".join((title or "").split())
    if not title:
        raise EditError("Give the new chapter a title.")
    new = Chapter(title=title, paragraphs=chapter.paragraphs[paragraph:])
    pages = [s.location.page for p in new.paragraphs for s in p.spans if s.location.page]
    if before and before.start_page:
        new.start_page = before.start_page
    else:
        new.start_page = pages[0] if pages else None
    new.merged = [
        MergedTitle(m.paragraph - paragraph, m.title, m.start_page)
        for m in chapter.merged
        if m.paragraph > paragraph
    ]
    chapter.merged = [m for m in chapter.merged if m.paragraph < paragraph]
    chapter.paragraphs = chapter.paragraphs[:paragraph]
    book.chapters.insert(index + 1, new)


def _chapter(book: Book, index: int) -> Chapter:
    if not 0 <= index < len(book.chapters):
        raise EditError(f"There's no chapter {index + 1}.")
    return book.chapters[index]
