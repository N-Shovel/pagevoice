"""Review edits (restore, rename, merge, split) and saving them between sessions."""

from dataclasses import asdict
from pathlib import Path

import pytest

from pagevoice import project
from pagevoice.document import Book, Chapter, Paragraph, Reason, Span
from pagevoice.edit import EditError, merge_with_next, rename_chapter, set_restored, split_at
from pagevoice.ingest import read_book

LANTERN = Path(__file__).parent / "corpus" / "public" / "trap-lantern" / "book.pdf"


def small_book() -> Book:
    def chapter(title, *texts, notes=()):
        return Chapter(
            title,
            [Paragraph.plain(title, kind="heading")] + [Paragraph.plain(t) for t in texts],
            [Paragraph.plain(n, kind="note") for n in notes],
        )

    return Book(
        "B",
        chapters=[
            chapter("One", "a", "b", notes=("note 1",)),
            chapter("Two", "c"),
            chapter("Three", "d"),
        ],
    )


def test_restore_and_remove_again():
    span = Span("Page 12", Reason.PAGE_NUMBER)
    paragraph = Paragraph([Span("Text "), span])
    assert paragraph.text == "Text"
    set_restored(span, True)
    assert paragraph.text == "Text Page 12"
    set_restored(span, False)
    assert paragraph.text == "Text"
    with pytest.raises(EditError):
        set_restored(Span("kept"), True)


def test_rename():
    book = small_book()
    rename_chapter(book, 1, "  The   Second  ")
    assert book.chapters[1].title == "The Second"
    with pytest.raises(EditError):
        rename_chapter(book, 1, "   ")
    with pytest.raises(EditError):
        rename_chapter(book, 9, "x")


def test_merge_keeps_every_paragraph_and_note():
    book = small_book()
    merge_with_next(book, 0)
    assert [c.title for c in book.chapters] == ["One", "Three"]
    assert book.chapters[0].readable() == ["One", "a", "b", "Two", "c", "note 1"]
    with pytest.raises(EditError):
        merge_with_next(book, 1)  # the last chapter


def test_split_takes_the_heading_as_title():
    book = small_book()
    merge_with_next(book, 0)
    split_at(book, 0, 3)  # at the "Two" heading
    assert [c.title for c in book.chapters] == ["One", "Two", "Three"]
    assert book.chapters[1].readable() == ["Two", "c"]
    assert book.chapters[0].readable() == ["One", "a", "b", "note 1"]  # notes stay first
    split_at(book, 0, 2, title="Second half")
    assert [c.title for c in book.chapters][:2] == ["One", "Second half"]
    with pytest.raises(EditError):
        split_at(book, 0, 0)


def test_split_without_heading_needs_a_title():
    book = small_book()
    with pytest.raises(EditError, match="title"):
        split_at(book, 0, 2)  # the engine doesn't make up English titles (rule 7)
    split_at(book, 0, 2, title="Part B")
    assert book.chapters[1].title == "Part B"


def test_split_after_merge_restores_the_old_title():
    book = small_book()
    book.chapters[1].title = "Two, from the bookmarks"  # not the heading text
    book.chapters[1].start_page = 7
    merge_with_next(book, 0)
    merge_with_next(book, 0)
    split_at(book, 0, 3)
    assert book.chapters[1].title == "Two, from the bookmarks"
    assert book.chapters[1].start_page == 7
    split_at(book, 1, 2)  # where "Three" began, remembered across the first split
    assert [c.title for c in book.chapters] == ["One", "Two, from the bookmarks", "Three"]


def test_review_edits_survive_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEVOICE_PROJECTS_DIR", str(tmp_path))
    book = read_book(LANTERN)
    removed = book.removals[0]
    set_restored(removed, True)
    rename_chapter(book, 0, "Renamed")
    book.cover, book.cover_type = b"\x89PNG fake", "image/png"
    key = project.book_id(LANTERN)
    project.save(book, key, source=LANTERN)
    loaded = project.load(key)
    assert asdict(loaded) == asdict(book)
    assert loaded.removals[0].restored and loaded.chapters[0].title == "Renamed"
    project.forget(key)
    assert project.load(key) is None


def test_unreadable_saved_review_is_kept_and_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEVOICE_PROJECTS_DIR", str(tmp_path))
    (tmp_path / "abc.json").write_text('{"format": 999}', encoding="utf-8")
    with pytest.raises(project.SavedReviewUnreadable) as info:
        project.load("abc")
    assert info.value.backup.read_text(encoding="utf-8") == '{"format": 999}'
    assert project.load("abc") is None  # moved aside: the next open starts fresh
    assert project.load("missing") is None


def test_book_id_is_the_file_content_not_its_name(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("same", encoding="utf-8")
    b.write_text("same", encoding="utf-8")
    assert project.book_id(a) == project.book_id(b)
    b.write_text("different", encoding="utf-8")
    assert project.book_id(a) != project.book_id(b)


def test_save_retries_while_the_file_is_busy(tmp_path, monkeypatch):
    """Windows refuses to replace a file another program has open; that passes quickly."""
    monkeypatch.setenv("PAGEVOICE_PROJECTS_DIR", str(tmp_path))
    real_replace, failures = project.os.replace, [PermissionError, PermissionError]

    def flaky(src, dst):
        if failures:
            raise failures.pop()
        real_replace(src, dst)

    monkeypatch.setattr(project.os, "replace", flaky)
    monkeypatch.setattr(project.time, "sleep", lambda _s: None)
    project.save(small_book(), "busy")
    assert project.load("busy").chapters[0].title == "One"
    assert not list(tmp_path.glob("*.tmp"))
