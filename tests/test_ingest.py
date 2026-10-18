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


def make_epub(path: Path, *, encryption: str | None = None, one: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        if encryption:
            z.writestr("META-INF/encryption.xml", encryption)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/nav.xhtml", NAV)
        z.writestr("OEBPS/text/one.xhtml", one or ONE)
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


# --- review fixes (M1 spec review) --------------------------------------------------

INNER_ID = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><h1>Chapter One</h1>
<p>Text with a note<a epub:type="noteref" href="#fn1">1</a> here.</p>
<p>A picture: <img src="p.png" alt="A lighthouse at night"/> and maths
<math alttext="x squared"><mi>x</mi></math>.</p>
<h2><img src="h.png" alt="Chapter Two Begins"/></h2>
<p>Gutenberg style<a class="fnanchor" href="#Footnote_2">[2]</a> marker.</p>
<aside epub:type="footnote"><p id="fn1">The note, with its id inside.</p></aside>
<div class="footnote"><p><a id="Footnote_2" href="#FNanchor_2" class="label">[2]</a>
A Gutenberg note.</p></div>
</body></html>"""
POPUP_SPINE = OPF.replace('<itemref idref="notes"/>', '<itemref idref="notes" linear="no"/>')


def test_epub_note_with_inner_id_moves_to_the_end(tmp_path):
    book = read_book(_rebuild(tmp_path, {"OEBPS/text/one.xhtml": INNER_ID}))
    one = book.chapters[0]
    body = " ".join(one.readable(drop_notes=True))
    assert "The note, with its id inside" not in body
    assert "A Gutenberg note" not in body and "[2]" not in body
    notes = " ".join(n.text for n in one.notes)
    assert "The note, with its id inside." in notes and "A Gutenberg note." in notes
    assert "Chapter Two Begins" in body  # heading drawn as a picture is read
    figures = [s.text for s in all_spans(book) if s.reason is Reason.FIGURE]
    assert "A lighthouse at night" in figures and any("x squared" in f for f in figures)


def _rebuild(tmp_path: Path, replace: dict[str, str], opf: str = OPF) -> Path:
    path = tmp_path / "rebuilt.epub"
    files = {
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": opf,
        "OEBPS/nav.xhtml": NAV,
        "OEBPS/text/one.xhtml": ONE,
        "OEBPS/text/two.xhtml": TWO,
        "OEBPS/text/notes.xhtml": NOTES,
        **replace,
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        for name, text in files.items():
            z.writestr(name, text)
    return path


def test_epub_non_linear_notes_are_found_and_the_rest_kept(tmp_path):
    book = read_book(_rebuild(tmp_path, {}, opf=POPUP_SPINE))
    assert any("An endnote" in n.text for n in book.chapters[0].notes)
    kept = [s.text for s in all_spans(book) if s.reason is Reason.NON_LINEAR]
    assert any("Never cited" in t for t in kept)  # not read, not lost
    assert not any("Never cited" in t for c in book.chapters for t in c.readable())


def test_non_english_books_are_refused_plainly(tmp_path):
    french = OPF.replace("<dc:language>en</dc:language>", "<dc:language>fr</dc:language>")
    with pytest.raises(IngestError, match="English books only"):
        read_book(_rebuild(tmp_path, {}, opf=french))
    # The reader can override a wrong label.
    assert read_book(_rebuild(tmp_path, {}, opf=french), language="en").language == "en"


def test_language_codes_are_normalised(tmp_path):
    for code in ("eng", "English", "en_GB"):
        opf = OPF.replace(">en</dc:language>", f">{code}</dc:language>")
        assert read_book(_rebuild(tmp_path, {}, opf=opf)).language.startswith("en")


GUTENBERG_NOTES = """CHAPTER I.

The lamp was lit[1] and the sea was calm.[A]

[Footnote 1: Whale oil, in those days.]

[Footnote A: A note that runs

over two blocks.]

The night went on.
"""


def test_txt_gutenberg_footnotes(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text(GUTENBERG_NOTES, encoding="utf-8")
    chapter = read_book(path).chapters[0]
    body = chapter.readable(drop_notes=True)
    assert body == ["CHAPTER I.", "The lamp was lit and the sea was calm.", "The night went on."]
    notes = [n.text for n in chapter.notes]
    assert notes[0].startswith("Whale oil") and "over two blocks." in notes[1]


def test_txt_unclosed_illustration_stops(tmp_path):
    text = "CHAPTER I.\n\n[Illustration: never closed\n\n" + "\n\n".join(
        f"Paragraph {n} of the story." for n in range(10)
    )
    path = tmp_path / "open.txt"
    path.write_text(text, encoding="utf-8")
    readable = read_book(path).chapters[0].readable()
    assert "Paragraph 9 of the story." in readable  # the book isn't silenced


def test_txt_locations_are_blocks(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text(GUTENBERG, encoding="utf-8")
    removal = next(s for s in all_spans(read_book(path)) if s.reason)
    assert removal.location.block is not None and removal.location.top is None


def test_copy_protected_pdf_is_refused(tmp_path):
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen.canvas import Canvas

    path = tmp_path / "locked.pdf"
    canvas = Canvas(str(path), encrypt=StandardEncryption("", canCopy=0))
    canvas.drawString(72, 700, "A protected page of text.")
    canvas.save()
    with pytest.raises(IngestError, match="protected"):
        read_book(path)


def test_two_bookmarks_on_one_page_both_survive(tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    path = tmp_path / "marks.pdf"
    canvas = Canvas(str(path))
    for number, titles in enumerate([["Part One", "The Start"], ["The Middle"]]):
        for index, title in enumerate(titles):
            key = f"k{number}{index}"
            canvas.bookmarkPage(key)
            canvas.addOutlineEntry(title, key, level=0)
        canvas.drawString(72, 700, f"Text on page {number + 1}.")
        canvas.showPage()
    canvas.save()
    titles = [c.title for c in read_book(path).chapters]
    assert any("Part One" in t for t in titles) and any("The Start" in t for t in titles)


def _scan_pdf(path: Path, pages: int, stamp_page: int | None, text_pages: int = 0) -> Path:
    """Page-sized pictures (a scan), optionally a short text stamp on one of them, then
    some ordinary text pages."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from tests.test_export import tiny_png

    picture = ImageReader(__import__("io").BytesIO(tiny_png()))
    width, height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    for number in range(1, pages + 1):
        pdf.drawImage(picture, 0, 0, width, height)
        if number == stamp_page:
            pdf.setFont("Helvetica", 9)
            pdf.drawString(72, 40, "Digitized by the Example Library")
        pdf.showPage()
    for _ in range(text_pages):
        pdf.setFont("Helvetica", 11)
        for row in range(30):
            pdf.drawString(72, height - 72 - row * 16, f"An ordinary line of book text, row {row}.")
        pdf.showPage()
    pdf.save()
    return path


def test_scan_with_a_text_stamp_is_refused(tmp_path):
    """A library scan with one "Digitized by" line must not become an audiobook of that
    line (SPEC §3: never read out garbage)."""
    with pytest.raises(IngestError, match="OCR"):
        read_book(_scan_pdf(tmp_path / "scan.pdf", 6, stamp_page=1))


def test_a_few_scanned_plates_are_flagged_not_refused(tmp_path):
    book = read_book(_scan_pdf(tmp_path / "plates.pdf", 2, stamp_page=1, text_pages=4))
    assert [(f.page, f.kind) for f in book.flags] == [(1, "scanned"), (2, "scanned")]


def test_pdf_pages_are_closed_as_they_are_read(monkeypatch):
    """pdfplumber keeps every page's objects until the page is closed (~5 MB a page).
    Closing them all when the file closes is too late: each must close before the next."""
    from pdfplumber.page import Page

    closed, seen = [], []
    real_close, real_words = Page.close, Page.extract_words
    monkeypatch.setattr(Page, "close", lambda self: closed.append(1) or real_close(self))

    def words(self, *args, **kwargs):
        seen.append(len(closed))  # pages closed before this one is read
        return real_words(self, *args, **kwargs)

    monkeypatch.setattr(Page, "extract_words", words)
    read_book(TRAPS / "trap-lantern" / "book.pdf")
    assert len(seen) > 2 and seen == list(range(len(seen)))


ONE_MARKERS = """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head><body>
<h1>Chapter One</h1>
<p>The war ended in spring.<a href="#fn3"><sup>3</sup></a> Nobody believed it.</p>
<p>See <a href="#ch2"><sup>the</sup> next chapter</a> and chapter <a href="#ch2">2</a>.</p>
<p><svg xmlns="http://www.w3.org/2000/svg"><title>A map of the coast</title></svg>After.</p>
<aside id="fn3"><p>3 The treaty came later.</p></aside>
</body></html>"""


def test_epub_link_around_superscript_is_a_note_marker(tmp_path):
    """Review finding 6: <a href="#fn"><sup>1</sup></a> (Calibre, many publishers)."""
    book = read_book(make_epub(tmp_path / "m.epub", one=ONE_MARKERS))
    first = book.chapters[0]
    texts = [p.text for p in first.paragraphs]
    assert "The war ended in spring. Nobody believed it." in texts
    markers = [s for s in all_spans(book) if s.reason == Reason.FOOTNOTE_MARKER]
    assert "3" in [s.text for s in markers]  # kept as a restorable removal
    # Ordinary links stay read: longer text, or no superscript.
    assert "See the next chapter and chapter 2." in texts


def test_epub_svg_title_is_a_figure_removal(tmp_path):
    """Rule 2: an SVG's <title> (its description) is kept as a removal, not dropped."""
    book = read_book(make_epub(tmp_path / "s.epub", one=ONE_MARKERS))
    figures = [s.text for s in all_spans(book) if s.reason == Reason.FIGURE]
    assert "A map of the coast" in figures
    assert "One" not in [s.text.strip() for s in all_spans(book)]  # <head><title> isn't text


def _spaced_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Word-export style: body text with a blank line's space between paragraphs, so
    each paragraph stands apart from the next (as running heads do)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    for paragraphs in pages:
        pdf.setFont("Helvetica", 11)
        y = A4[1] - 72
        for paragraph in paragraphs:
            for line in paragraph.split("\n"):
                pdf.drawString(72, y, line)
                y -= 15
            y -= 15  # space after the paragraph
        pdf.showPage()
    pdf.save()
    return path


WORDS = [
    "lamp",
    "gull",
    "rope",
    "tide",
    "boat",
    "stone",
    "wind",
    "salt",
    "mast",
    "bell",
    "oar",
    "net",
    "fog",
    "cliff",
    "wave",
    "reef",
]


def filler(page: int, part: int) -> str:
    """Body text that differs on every page in its words (running-head detection ignores
    digits, and text repeating at the top of most pages is a running head)."""
    pick = [WORDS[(page * 7 + part * 3 + n) % len(WORDS)] for n in range(9)]
    return "\n".join(
        f"The keeper found the {pick[3 * n]} by the {pick[3 * n + 1]} near the {pick[3 * n + 2]}."
        for n in range(3)
    )


def test_top_lines_shaped_like_numbered_heads_are_kept(tmp_path):
    """Review finding 14: one page starting "I never…" or ending "…1914" isn't a head."""
    pages = [
        [filler(1, 1), filler(1, 2)],
        ["I never saw him again after that summer.", filler(2, 1)],
        ["and the bill came to 1914", filler(3, 1)],
        [filler(4, 1), filler(4, 2)],
    ]
    book = read_book(_spaced_pdf(tmp_path / "word.pdf", pages))
    text = " ".join(p.text for c in book.chapters for p in c.paragraphs)
    assert "I never saw him again after that summer." in text
    assert "and the bill came to 1914" in text
    assert not [s for s in book.removals if s.reason == Reason.HEADER]


def test_recurring_numbered_heads_are_still_removed(tmp_path):
    pages = [[f"{n} THE LANTERN KEEPER", filler(n, 1)] for n in range(2, 8)]
    book = read_book(_spaced_pdf(tmp_path / "heads.pdf", pages))
    heads = [s for s in book.removals if s.reason == Reason.HEADER]
    assert len(heads) == 6 and all(s.location.page for s in heads)


def _drop_cap_pdf(path: Path, openings: list[tuple[str, str]]) -> Path:
    """Each page opens with a big drop-cap letter beside the rest of its first line, then
    ordinary lines that use some words again (the evidence the rule looks for)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    for cap, rest in openings:
        top = A4[1] - 100
        pdf.setFont("Helvetica", 40)
        pdf.drawString(72, top - 20, cap)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(104, top, rest)
        for n, line in enumerate(
            ["The lamp was long and the night was long.", "He was there and so was she."]
        ):
            pdf.drawString(72, top - 60 - 15 * n, line)
        pdf.showPage()
    pdf.save()
    return path


@pytest.mark.parametrize(
    ("cap", "rest", "reads"),
    [
        ("T", "he tower stood alone.", "The tower stood alone."),
        ("I", "t stood alone.", "It stood alone."),
        ("I", "was born in the village.", "I was born in the village."),
        ("A", "long time ago it stood.", "A long time ago it stood."),
    ],
)
def test_drop_caps_join_only_with_evidence(tmp_path, cap, rest, reads):
    """Review finding 12: "I" + "was" became "Iwas", "A" + "long" became "Along"."""
    book = read_book(_drop_cap_pdf(tmp_path / "cap.pdf", [(cap, rest)]))
    text = " ".join(p.text for c in book.chapters for p in c.paragraphs)
    assert text.startswith(reads)


def test_text_drawn_twice_is_read_once(tmp_path):
    """Review finding 15: "fake bold" (the same text drawn twice, a hair apart)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "bold.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setFont("Helvetica", 20)
    for dx in (0, 0.4):
        pdf.drawString(72 + dx, A4[1] - 100, "Chapter 1")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, A4[1] - 140, "The tower stood alone on the rock.")
    pdf.save()
    book = read_book(path)
    text = " ".join(p.text for c in book.chapters for p in c.paragraphs)
    assert "Chapter 1" in text and "CChh" not in text


@pytest.mark.parametrize(
    ("text", "caption"),
    [
        ("Figure 1. The lantern room at dusk.", True),
        ("Table 2: Harvests by year", True),
        ("Fig. 3 The coast at low tide", True),
        ("Plate IV", True),
        ("Table 2 shows that the harvest doubled between the two surveys.", False),
        ("Figure 3 makes the point clearer than any table could.", False),
    ],
)
def test_captions_need_a_caption_shape(text, caption):
    """Review finding 13: body sentences that begin "Table 2 …" aren't captions."""
    from pagevoice.cleanup.en import is_caption

    assert is_caption(text) is caption
