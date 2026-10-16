"""Readers and cleanup rules. Every removal keeps its text, reason and location.

PDF tests use the trap PDFs in tests/corpus/public/trap-* (made by tools/make_trap_pdfs.py).
EPUB and TXT tests build small files on the fly; the golden corpus checks real books.
"""

import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from pagevoice.cleanup.text import fix_characters, should_rejoin, word_counts
from pagevoice.document import Book, IngestError, Reason
from pagevoice.ingest import read_book

TRAPS = Path(__file__).resolve().parent / "corpus" / "public"


def all_spans(book: Book):
    for chapter in book.chapters:
        for paragraph in [*chapter.paragraphs, *chapter.notes]:
            yield from paragraph.spans


def reasons(book: Book) -> Counter:
    return Counter(s.reason for s in all_spans(book) if s.reason)


def words_of(text: str) -> Counter:
    return Counter(re.findall(r"[^\W\d_]+|\d+", text.lower()))


# --- shared text rules --------------------------------------------------------------


def test_ligatures_and_soft_hyphens_are_repaired():
    assert fix_characters("ﬁne ﬂowers, watch­man") == "fine flowers, watchman"


def test_hyphen_rejoin_needs_evidence():
    counts = word_counts(["an extraordinary thing", "a well-known man"])
    assert should_rejoin("extra", "ordinary", counts)  # joined form seen elsewhere
    assert not should_rejoin("well", "known", counts)  # hyphenated form seen elsewhere
    assert should_rejoin("some", "thing", word_counts(["nothing here"]))  # no evidence


# --- TXT ----------------------------------------------------------------------------

GUTENBERG = """The Project Gutenberg eBook of A Short Test

Title: A Short Test
Author: Nobody

*** START OF THE PROJECT GUTENBERG EBOOK A SHORT TEST ***

CONTENTS

CHAPTER I.

CHAPTER II.

CHAPTER III.

[Illustration:

CHAPTER I.]

It was a _very_ dark night, and the rain
fell in torrents.

[Illustration: A lamp]

The wind was well-known on that coast.

CHAPTER II.

Morning came.

CHAPTER III.

The end.

*** END OF THE PROJECT GUTENBERG EBOOK A SHORT TEST ***

Licence text here.
"""


def test_txt_gutenberg(tmp_path):
    path = tmp_path / "book.txt"
    path.write_bytes(b"\xef\xbb\xbf" + GUTENBERG.encode("utf-8"))
    book = read_book(path)
    assert (book.title, book.author) == ("A Short Test", "Nobody")
    titles = [c.title for c in book.chapters]
    assert titles == ["CHAPTER I.", "CHAPTER II.", "CHAPTER III."]
    first = book.chapters[0].readable()
    assert first[0] == "CHAPTER I."
    assert "It was a very dark night, and the rain fell in torrents." in first
    assert not any("Illustration" in t for c in book.chapters for t in c.readable())
    counted = reasons(book)
    assert counted[Reason.BOILERPLATE] >= 3 and counted[Reason.CAPTION] >= 2


def test_txt_keeps_every_word(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text(GUTENBERG, encoding="utf-8")
    book = read_book(path)
    kept = Counter()
    for span in all_spans(book):
        kept += words_of(span.text)
    source = words_of(GUTENBERG.replace("_", " "))
    assert not source - kept  # nothing silently dropped


def test_txt_windows_1252(tmp_path):
    path = tmp_path / "old.txt"
    path.write_bytes("Caf\xe9 \x93quoted\x94".encode("latin-1"))
    assert read_book(path).chapters[0].readable() == ["Café “quoted”"]


# --- EPUB ---------------------------------------------------------------------------

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf"
 media-type="application/oebps-package+xml"/></rootfiles></container>"""
OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Test Book</dc:title><dc:creator>A. Writer</dc:creator><dc:language>en</dc:language>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="text/one.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="text/two.xhtml" media-type="application/xhtml+xml"/>
<item id="notes" href="text/notes.xhtml" media-type="application/xhtml+xml"/>
<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
</manifest>
<spine><itemref idref="c1"/><itemref idref="c2"/><itemref idref="notes"/></spine>
</package>"""
NAV = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol>
<li><a href="text/one.xhtml">One</a></li><li><a href="text/two.xhtml">Two</a></li>
</ol></nav></body></html>"""
ONE = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>One</title><style>p {}</style></head><body>
<h1>Chapter One</h1>
<p><img alt="T" src="t.png"/>he lamp was lit.<a epub:type="noteref" href="notes.xhtml#n1">1</a>
The sea was calm.</p>
<table><tr><td>Tide</td><td>High</td></tr></table>
<figure><img src="x.png" alt=""/><figcaption>Figure 1. The lamp.</figcaption></figure>
<p>A second paragraph<sup><a href="#fn2">2</a></sup> here.</p>
<aside epub:type="footnote" id="fn2"><p>2 A local note.</p></aside>
</body></html>"""
TWO = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chapter Two</h1><p>Morning came.</p></body></html>"""
NOTES = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><section epub:type="endnotes"><h2>Notes</h2><ol>
<li id="n1" epub:type="endnote"><p>An endnote.
<a href="one.xhtml#r1" epub:type="backlink">↩</a></p></li>
<li id="n9" epub:type="endnote"><p>Never cited.</p></li>
</ol></section></body></html>"""


def make_epub(path: Path, *, encryption: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        if encryption:
            z.writestr("META-INF/encryption.xml", encryption)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/nav.xhtml", NAV)
        z.writestr("OEBPS/text/one.xhtml", ONE)
        z.writestr("OEBPS/text/two.xhtml", TWO)
        z.writestr("OEBPS/text/notes.xhtml", NOTES)
        z.writestr("OEBPS/cover.jpg", b"\xff\xd8fakejpeg")
    return path


def test_epub_reads_chapters_notes_and_removals(tmp_path):
    book = read_book(make_epub(tmp_path / "t.epub"))
    assert (book.title, book.author, book.language) == ("Test Book", "A. Writer", "en")
    assert book.cover_type == "image/jpeg"
    one = book.chapters[0]
    assert one.title == "Chapter One"
    text = one.readable(drop_notes=True)
    assert text[1] == "The lamp was lit. The sea was calm."  # drop cap joined, marker out
    assert "A second paragraph here." in text
    assert not any("Tide" in t or "Figure" in t for t in text)
    notes = [n.text for n in one.notes]
    assert "An endnote." in notes[0] or notes[0].startswith("An endnote")
    assert any("A local note" in n for n in notes)  # never read inline (D11)
    counted = reasons(book)
    assert counted[Reason.FOOTNOTE_MARKER] >= 2
    assert counted[Reason.TABLE] >= 2 and counted[Reason.CAPTION] >= 1
    # The uncited note stays with its own section, at the end, not inline.
    assert all(p.kind != "note" for c in book.chapters for p in c.paragraphs)
    assert any("Never cited" in n.text for c in book.chapters for n in c.notes)


def test_epub_drm_is_refused(tmp_path):
    enc = """<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
    xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    </enc:EncryptedData></encryption>"""
    with pytest.raises(IngestError, match="DRM"):
        read_book(make_epub(tmp_path / "drm.epub", encryption=enc))


def test_epub_font_obfuscation_is_not_drm(tmp_path):
    enc = """<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
    xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
    </enc:EncryptedData></encryption>"""
    assert read_book(make_epub(tmp_path / "fonts.epub", encryption=enc)).chapters


@pytest.mark.parametrize("suffix", [".mobi", ".azw3"])
def test_kindle_formats_point_to_calibre(tmp_path, suffix):
    path = tmp_path / f"book{suffix}"
    path.write_bytes(b"x")
    with pytest.raises(IngestError, match="Calibre"):
        read_book(path)


# --- PDF ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lantern() -> Book:
    return read_book(TRAPS / "trap-lantern" / "book.pdf")


def test_pdf_headers_footers_and_page_numbers(lantern):
    counted = reasons(lantern)
    assert counted[Reason.PAGE_NUMBER] >= 6
    assert counted[Reason.HEADER] >= 3
    removed = [s.text for s in all_spans(lantern) if s.reason is Reason.HEADER]
    assert "THE LANTERN KEEPER" in removed and "The Tower" in removed
    for span in all_spans(lantern):
        if span.reason in (Reason.HEADER, Reason.PAGE_NUMBER):
            assert span.location.page and span.location.top is not None


def test_pdf_footnotes_move_to_chapter_end(lantern):
    chapter = next(c for c in lantern.chapters if c.title.startswith("CHAPTER I:"))
    assert [n.text[:2] for n in chapter.notes] == ["1 ", "2 "]
    body = " ".join(chapter.readable(drop_notes=True))
    assert "Sea pinks" not in body and "wall and who spoke" in body
    markers = [s for s in all_spans(lantern) if s.reason is Reason.FOOTNOTE_MARKER]
    assert [m.text for m in markers] == ["1", "2"]


def test_pdf_hyphens_follow_the_evidence_rule(lantern):
    text = " ".join(t for c in lantern.chapters for t in c.readable())
    assert "though the extraordinary volume of self-taught seamanship" in text
    hyphens = [s for s in all_spans(lantern) if s.reason is Reason.HYPHEN]
    assert len(hyphens) == 1  # only "extra-ordinary" lost its hyphen


def test_pdf_traps_are_repaired(lantern):
    text = " ".join(t for c in lantern.chapters for t in c.readable())
    assert "The Tower Stood on a ledge" in text  # drop cap + small caps
    assert "fine garden of flowers" in text  # ligatures
    assert "only watchman on" in text  # soft hyphen
    assert "Figure 1" not in text
    assert any(s.reason is Reason.CAPTION for s in all_spans(lantern))


def test_pdf_paragraph_runs_over_page_break(lantern):
    paragraphs = [p for c in lantern.chapters for p in c.paragraphs if p.text]
    pages = [{s.location.page for s in p.spans if not s.removed} for p in paragraphs]
    assert {2, 3} in pages  # "The supply boat came ..." starts on 2, ends on 3


def test_pdf_keeps_every_word(lantern):
    """Nothing deleted silently: every extracted word is in the book, kept or removed."""
    from pagevoice.ingest.pdf import extract

    extracted = Counter()
    for page in extract(TRAPS / "trap-lantern" / "book.pdf").pages:
        for line in page.lines:
            extracted += words_of(line.text)
    kept = Counter()
    for chapter in lantern.chapters:
        for paragraph in [*chapter.paragraphs, *chapter.notes]:
            kept += words_of(paragraph.original)
    # Small caps and drop caps change case and joins, not words; compare case-folded.
    # Rejoined split words ("extra" + "ordinary") are counted as one word in the book.
    # So are the drop cap and its word ("T" + "he" is "The").
    missing = extracted - kept - Counter({"extra": 1, "ordinary": 1, "t": 1, "he": 1})
    assert not missing


def test_pdf_chapters_from_bookmarks():
    book = read_book(TRAPS / "trap-bookmarks" / "book.pdf")
    assert [c.title for c in book.chapters] == ["The Harbour", "The Crossing", "Home Again"]


def test_pdf_two_column_page_is_flagged_not_read():
    book = read_book(TRAPS / "trap-two-column" / "book.pdf")
    assert [(f.page, f.kind) for f in book.flags] == [(2, "multi_column")]
    assert all(s.reason is Reason.MULTI_COLUMN for s in all_spans(book) if s.location.page == 2)


def test_pdf_scanned_pages_are_flagged():
    book = read_book(TRAPS / "trap-scanned-page" / "book.pdf")
    assert [(f.page, f.kind) for f in book.flags] == [(2, "scanned"), (3, "scanned")]


def test_pdf_without_text_is_refused_plainly():
    with pytest.raises(IngestError, match="OCR"):
        read_book(TRAPS / "trap-scanned" / "book.pdf")


def test_pdf_word_export_reads_in_position_order():
    """Words drawn one by one, lines out of order: reading order comes from positions."""
    book = read_book(TRAPS / "trap-word-export" / "book.pdf")
    text = book.chapters[0].readable()
    assert text[0].startswith("The keeper climbed the stair each evening")
    assert reasons(book)[Reason.PAGE_NUMBER] == 2
    assert not book.chapters[0].notes
