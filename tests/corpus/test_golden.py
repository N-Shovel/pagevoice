"""Golden corpus: every hand-checked page must come out exactly as expected.

Pages live in tests/corpus/<public|private>/<book>/expected/page-NNN.txt and are
human-owned. Books whose file isn't downloaded (tools/corpus.py fetch) are skipped, and so
are books with no expected pages yet.
"""

import difflib

import pytest

from pagevoice.ingest import read_book

from .golden import books, normalise, render_page


def _marks(book):
    # Big books take tens of seconds to read: CI runs them in a separate step.
    big = book.meta.get("format") != "txt" and book.folder.name.startswith(
        ("archive-", "gutenberg-")
    )
    return [pytest.mark.slow] if big else []


CASES = [
    pytest.param(book, number, path, id=f"{book.id}-{number:03d}", marks=_marks(book))
    for book in books()
    for number, path in book.golden_pages().items()
]
_cache: dict[str, object] = {}


def _read(book):
    if book.id not in _cache:
        _cache[book.id] = read_book(book.path)
    return _cache[book.id]


@pytest.mark.skipif(not CASES, reason="no golden pages in expected/ yet")
@pytest.mark.parametrize(("book", "number", "path"), CASES)
def test_golden_page(book, number, path):
    if not book.available():
        pytest.skip(f"{book.id}: book file not downloaded (run tools/corpus.py fetch)")
    want = normalise(path.read_text(encoding="utf-8"))
    got = normalise(render_page(_read(book), number, book.unit))
    if got != want:
        diff = "\n".join(
            difflib.unified_diff(
                want.splitlines(), got.splitlines(), "expected", "got", lineterm=""
            )
        )
        pytest.fail(f"{book.id} page {number} differs:\n{diff}")


FLAG_CASES = [
    pytest.param(book, id=book.id, marks=_marks(book))
    for book in books()
    if "multi_column_share" in book.meta
]


@pytest.mark.skipif(not FLAG_CASES, reason="no books with flag expectations")
@pytest.mark.parametrize("book", FLAG_CASES)
def test_multi_column_pages_are_flagged(book):
    """Two-column books: most pages must be flagged, never read as interleaved text."""
    if not book.available():
        pytest.skip(f"{book.id}: book file not downloaded (run tools/corpus.py fetch)")
    parsed = _read(book)
    flagged = {f.page for f in parsed.flags if f.kind == "multi_column"}
    pages = {s.location.page for c in parsed.chapters for p in c.paragraphs for s in p.spans}
    pages.discard(None)
    assert len(flagged) >= book.meta["multi_column_share"] * len(pages)
