"""PDF with a text layer, via pdfplumber (D5: never PyMuPDF).

This module only extracts: words with font size and position, grouped into lines, plus
bookmarks and metadata. Deciding what is a header, footnote or chapter is cleanup's job
(cleanup/pdf.py).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pagevoice.cleanup.text import fix_characters
from pagevoice.document import Book, IngestError

log = logging.getLogger(__name__)

SCANNED_MESSAGE = (
    "This PDF is a scan with no text, so PageVoice can't read it. Run it through OCR "
    "first (for example with OCRmyPDF), then open the new PDF."
)
ENCRYPTED_MESSAGE = (
    "This PDF is password-protected or DRM-protected, so PageVoice can't read it. "
    "PageVoice never removes protection."
)


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    font: str
    space_before: bool = True  # False when it touches the previous word (e.g. "word¹")


@dataclass
class Line:
    words: list[Word]
    page: int  # 1-based

    @property
    def text(self) -> str:
        out = ""
        for word in self.words:
            out += (" " if out and word.space_before else "") + word.text
        return out

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.main_words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.main_words)

    @property
    def size(self) -> float:
        """The size most of the line's characters are set in."""
        weights: dict[float, int] = {}
        for word in self.words:
            key = round(word.size, 1)
            weights[key] = weights.get(key, 0) + len(word.text)
        return max(weights, key=weights.get)

    @property
    def main_words(self) -> list[Word]:
        size = self.size
        main = [w for w in self.words if abs(w.size - size) < 0.6]
        return main or self.words


SCAN_COVER = 0.8  # an image covering this much of the page...
SCAN_MAX_WORDS = 25  # ...under fewer words than this is a scanned page
SCANS_TO_REFUSE = 0.8  # refuse a PDF when at least this share of its pages are scans


@dataclass
class Page:
    number: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    has_images: bool = False
    image_cover: float = 0.0  # share of the page the largest image covers
    tables: list[tuple[float, float, float, float]] = field(default_factory=list)  # bboxes
    rules: list[float] = field(default_factory=list)  # y of short horizontal lines

    @property
    def is_scan(self) -> bool:
        """A picture of a page: no text, or a page-sized image under a short text stamp
        ("Digitized by …"). An OCR'd scan has a full text layer, so it isn't one."""
        if not self.lines:
            return self.has_images
        words = sum(len(line.words) for line in self.lines)
        return self.image_cover >= SCAN_COVER and words < SCAN_MAX_WORDS


@dataclass
class Extracted:
    pages: list[Page]
    title: str
    author: str
    language: str
    bookmarks: list[tuple[str, int]]  # top-level (title, 1-based page)


def _lines(words: list[Word], page: int) -> list[Line]:
    """Group words into lines by vertical overlap, so raised markers stay in their line."""
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (round(w.top), w.x0)):
        height = max(word.bottom - word.top, 0.1)
        best = None
        for line in reversed(lines[-4:]):
            overlap = min(line.bottom, word.bottom) - max(line.top, word.top)
            line_height = max(line.bottom - line.top, 0.1)
            if overlap > 0.5 * min(height, line_height):
                best = line
                break
        if best is None:
            lines.append(Line([word], page))
        else:
            best.words.append(word)
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
        for prev, word in zip(line.words, line.words[1:], strict=False):
            word.space_before = word.x0 - prev.x1 > 0.12 * min(word.size, prev.size)
    lines.sort(key=lambda ln: ln.top)
    return lines


def extract(path: Path) -> Extracted:
    import pdfplumber
    import pypdfium2
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    try:
        pdf = pdfplumber.open(path)
    except PDFPasswordIncorrect as exc:
        raise IngestError(ENCRYPTED_MESSAGE) from exc
    except Exception as exc:  # pdfminer raises many types for damaged files
        raise IngestError("This PDF is damaged, so PageVoice can't read it.") from exc

    pages: list[Page] = []
    with pdf:
        # Encrypted with an empty password but copying forbidden: that's the publisher
        # saying no. PageVoice never works around protection (SPEC §3).
        if getattr(pdf.doc, "encryption", None) and not pdf.doc.is_extractable:
            raise IngestError(ENCRYPTED_MESSAGE)
        meta = pdf.metadata or {}
        for index, raw in enumerate(pdf.pages, 1):
            page = Page(index, float(raw.width), float(raw.height))
            page.has_images = bool(raw.images)
            area = page.width * page.height or 1.0
            page.image_cover = max(
                (
                    (float(i["x1"]) - float(i["x0"]))
                    * (float(i["bottom"]) - float(i["top"]))
                    / area
                    for i in raw.images
                ),
                default=0.0,
            )
            words = raw.extract_words(
                extra_attrs=["size", "fontname"],
                keep_blank_chars=False,
                use_text_flow=False,
                x_tolerance=1.5,
            )
            page.lines = _lines(
                [
                    Word(
                        fix_characters(w["text"]),
                        float(w["x0"]),
                        float(w["x1"]),
                        float(w["top"]),
                        float(w["bottom"]),
                        float(w["size"]),
                        str(w["fontname"]),
                    )
                    for w in words
                    if fix_characters(w["text"]).strip()
                ],
                index,
            )
            try:
                page.tables = [t.bbox for t in raw.find_tables()]
            except Exception:  # table finding is best effort
                log.debug("Table detection failed on page %d", index, exc_info=True)
            page.rules = [
                float(e["top"])
                for e in raw.edges
                if e.get("orientation") == "h"
                and 20 < float(e["x1"]) - float(e["x0"]) < 0.6 * page.width
            ]
            pages.append(page)
            raw.close()  # pdfplumber caches each page's objects until closed (~5 MB a page)
        language = ""
        try:
            lang = pdf.doc.catalog.get("Lang")
            language = lang.decode() if isinstance(lang, bytes) else str(lang or "")
        except Exception:
            language = ""

    bookmarks: list[tuple[str, int]] = []
    try:
        doc = pypdfium2.PdfDocument(str(path))
        for item in doc.get_toc():
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            if item.level == 0 and index is not None:
                bookmarks.append((item.get_title().strip(), index + 1))
        doc.close()
    except Exception:
        log.debug("No readable bookmarks", exc_info=True)

    return Extracted(
        pages=pages,
        title=_meta_text(meta.get("Title")),
        author=_meta_text(meta.get("Author")),
        language=language,
        bookmarks=bookmarks,
    )


def _meta_text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").strip()


def read_pdf(path: Path, *, language: str | None = None) -> Book:
    from pagevoice.cleanup.pdf import build_book

    extracted = extract(path)
    pages = extracted.pages
    scans = sum(1 for page in pages if page.is_scan)
    # Mostly pictures of pages (perhaps with a text stamp): refuse plainly rather than make
    # an audiobook of the stamp (SPEC §3). A few scanned pages are only flagged in review.
    if not any(page.lines for page in pages) or (pages and scans / len(pages) >= SCANS_TO_REFUSE):
        raise IngestError(SCANNED_MESSAGE)
    return build_book(extracted, fallback_title=path.stem, language=language)
