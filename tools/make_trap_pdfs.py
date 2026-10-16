"""Make the trap PDFs for the golden corpus (tests/corpus/public/trap-*).

    uv run python tools/make_trap_pdfs.py

These are PDFs we made ourselves, so they can be committed. Each one is typeset from text
written here, so we know exactly what it should read like. The script writes:
- tests/corpus/public/<id>/book.pdf and book.toml
- tests/corpus/public/<id>/candidate/page-NNN.txt: the text each page should read as,
  in the tests/corpus/README.md format. A human checks these and moves them to expected/.

It never writes to expected/.

The text is original (written for PageVoice), in the public domain.
"""

import hashlib
import io
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

import reportlab
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus" / "public"
FONTS = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Vera", str(FONTS / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("VeraBd", str(FONTS / "VeraBd.ttf")))

W, H = letter
MARGIN = 72
BODY, LEADING = 11, 14.5
NOTE, NOTE_LEADING = 8.5, 11
INDENT = 18
TEXT_W = W - 2 * MARGIN


# --- a tiny typesetter -------------------------------------------------------------
# A paragraph is a list of tokens: (kind, text[, extra]).
#   w    word
#   sup  footnote marker, attached to the previous word; extra = note text
#   sc   word in small caps
#   dc   drop cap letter, attached to the next word
#   brk  word broken across lines at a hyphen: extra = index of the break


@dataclass
class Para:
    tokens: list[tuple]
    kind: str = "text"  # text, heading1, heading2, caption
    expected: str = ""  # what it should read as
    notes: list[str] = field(default_factory=list)


def words(text: str) -> list[tuple]:
    return [("w", w) for w in text.split()]


def para(*parts, kind="text") -> Para:
    tokens: list[tuple] = []
    for part in parts:
        tokens += words(part) if isinstance(part, str) else [part]
    return Para(tokens, kind)


def width(text: str, size: float = BODY, font: str = "Vera") -> float:
    return pdfmetrics.stringWidth(text, font, size)


def sc_width(text: str) -> float:
    return width(text[0]) + width(text[1:].upper(), BODY * 0.75)


class Book:
    def __init__(self, path: Path, title: str, *, page_numbers: str = "arabic") -> None:
        self.canvas = Canvas(str(path), pagesize=letter, invariant=1)
        self.canvas.setTitle(title)
        self.canvas.setAuthor("PageVoice test corpus")
        self.title = title
        self.page = 0
        self.chapter_title = ""
        self.y = 0.0
        self.notes: list[str] = []
        self.expected: dict[int, list[str]] = {}
        self.expected_notes: dict[int, list[str]] = {}
        self.page_numbers = page_numbers
        self.headers = True
        self.new_page(chapter_start=True)

    # pages
    def new_page(self, chapter_start: bool = False) -> None:
        if self.page:
            self.finish_page()
        self.page += 1
        self.y = H - MARGIN
        self.notes = []
        self.chapter_start = chapter_start

    def finish_page(self) -> None:
        c = self.canvas
        if self.headers and not self.chapter_start:
            text = self.title.upper() if self.page % 2 == 0 else self.chapter_title
            c.setFont("Vera", 9)
            c.drawCentredString(W / 2, H - 40, text)
        if self.page_numbers:
            c.setFont("Vera", 9)
            c.drawCentredString(W / 2, 36, str(self.page))
        if self.notes:
            y = MARGIN + self.notes_height(self.notes) - NOTE_LEADING + 2
            c.setLineWidth(0.5)
            c.line(MARGIN, y + NOTE_LEADING, MARGIN + 120, y + NOTE_LEADING)
            c.setFont("Vera", NOTE)
            for note in self.notes:
                for line in wrap_plain(note, NOTE):
                    c.drawString(MARGIN, y, line)
                    y -= NOTE_LEADING
        c.showPage()

    def notes_height(self, notes: list[str]) -> float:
        if not notes:
            return 0
        lines = sum(len(wrap_plain(n, NOTE)) for n in notes)
        return lines * NOTE_LEADING + NOTE_LEADING

    def close(self) -> None:
        self.finish_page()
        self.canvas.save()

    def record(self, text: str) -> None:
        self.expected.setdefault(self.page, []).append(text)

    # content
    def heading(self, text: str, size: float, expected: str | None = None) -> None:
        c = self.canvas
        self.y -= size * 1.6
        c.setFont("VeraBd", size)
        c.drawCentredString(W / 2, self.y, text)
        self.y -= size * 0.8
        self.record(expected or text)

    def chapter(self, number: str, title: str) -> None:
        if self.page > 1 or self.y < H - MARGIN:
            self.new_page(chapter_start=True)
        self.chapter_title = title
        self.y -= 60
        self.heading(number, 18)
        self.heading(title, 14)
        self.y -= 10

    def caption(self, text: str) -> None:
        c = self.canvas
        self.y -= 90
        c.rect(W / 2 - 80, self.y + 12, 160, 70)
        c.setFont("Vera", 9)
        c.drawCentredString(W / 2, self.y, text)
        self.y -= LEADING * 1.2

    def paragraph(self, p: Para, *, indent: bool = True, expected: str = "") -> None:
        lines = self.wrap(p, indent)
        first = True
        for line, notes in lines:
            room = self.y - LEADING - (MARGIN + 6 + self.notes_height(self.notes + notes))
            if room < 0:
                self.new_page()
            if first:
                self.record(expected)
                first = False
            self.y -= LEADING
            self.draw_line(line)
            for note in notes:
                self.notes.append(note)
                self.expected_notes.setdefault(self.page, []).append(note)
        self.y -= 3

    def wrap(self, p: Para, indent: bool) -> list[tuple[list, list[str]]]:
        """Greedy wrap into lines of (x, kind, text) pieces; forced breaks at 'brk'."""
        lines: list[tuple[list, list[str]]] = []
        x0 = MARGIN + (INDENT if indent else 0)
        x = x0
        line: list = []
        notes: list[str] = []
        drop_lines = 0
        tokens = list(p.tokens)
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind, text = token[0], token[1]
            if kind == "dc":
                line.append((MARGIN, "dc", text))
                x0 = MARGIN + width(text, BODY * 3.2, "VeraBd") + 4
                x = x0
                drop_lines = 3
                i += 1
                # the rest of the first word follows with no space
                nxt = tokens[i]
                line.append((x, "w", nxt[1]))
                x += width(nxt[1])
                i += 1
                continue
            if kind == "sup":
                line.append((x, "sup", text))
                x += width(text, BODY * 0.6)
                notes.append(token[2])
                i += 1
                continue
            piece = text
            if kind == "brk":  # "extra|ordinary" -> "extra-" at the end of the line
                piece = text[: token[2]]
                piece += "" if piece.endswith("-") else "-"
            piece_w = sc_width(piece) if kind == "sc" else width(piece)
            space = width(" ") if line else 0
            if x + space + piece_w > MARGIN + TEXT_W and line:
                lines.append((line, notes))
                line, notes = [], []
                if drop_lines:
                    drop_lines -= 1
                    if not drop_lines:
                        x0 = MARGIN
                x = x0 if drop_lines else MARGIN
                space = 0
            x += space
            line.append((x, "sc" if kind == "sc" else "w", piece))
            x += piece_w
            if kind == "brk":  # force the break, carry the rest to the next line
                lines.append((line, notes))
                line, notes = [], []
                if drop_lines:
                    drop_lines -= 1
                x = x0 if drop_lines else MARGIN
                rest = text[token[2] :]
                line.append((x, "w", rest))
                x += width(rest)
            i += 1
        if line:
            lines.append((line, notes))
        return lines

    def draw_line(self, line: list) -> None:
        c = self.canvas
        for x, kind, text in line:
            if kind == "dc":
                c.setFont("VeraBd", BODY * 3.2)
                c.drawString(x, self.y - BODY * 2.1, text)
            elif kind == "sup":
                c.setFont("Vera", BODY * 0.6)
                c.drawString(x, self.y + BODY * 0.4, text)
            elif kind == "sc":
                c.setFont("Vera", BODY)
                c.drawString(x, self.y, text[0])
                c.setFont("Vera", BODY * 0.75)
                c.drawString(x + width(text[0]), self.y, text[1:].upper())
            else:
                c.setFont("Vera", BODY)
                c.drawString(x, self.y, text)


def wrap_plain(text: str, size: float) -> list[str]:
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if width(trial, size) > TEXT_W and line:
            out.append(line)
            line = word
        else:
            line = trial
    return out + ([line] if line else [])


# --- the text -----------------------------------------------------------------------

FILLER = [
    "The keeper climbed the stair each evening with the same slow care, counting the "
    "steps under his breath as his father had done before him.",
    "Below the tower the sea worked at the rocks without rest, and the gulls rode the wind "
    "as if it had been built for them alone.",
    "He trimmed the wick, wiped the glass, and set the great lamp turning, so that its beam "
    "swept out across the water and back again.",
    "On clear nights he could see the lights of the fishing boats far out, small and "
    "steady, and he liked to think that they could see his light as well.",
    "In the morning he wrote the weather in the log: the wind, the sky, the height of the "
    "tide, and any ship that had passed in the dark.",
    "The supply boat came once a fortnight, weather allowing, with flour and oil and "
    "letters that were always a little older than he wished.",
]


def write_candidates(book_id: str, book: Book) -> None:
    folder = CORPUS / book_id / "candidate"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("page-*.txt"):
        old.unlink()
    for page in range(1, book.page + 1):
        lines = list(book.expected.get(page, []))
        if book.expected_notes.get(page):
            lines += ["[notes]", *book.expected_notes[page]]
        (folder / f"page-{page:03d}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )


def write_toml(book_id: str, pdf: Path, traps: list[str], pages: int, note: str) -> None:
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    checked = ", ".join(str(n) for n in range(1, pages + 1))
    (CORPUS / book_id / "book.toml").write_text(
        f'id = "{book_id}"\n'
        'format = "pdf"\n'
        'file = "book.pdf"\n'
        'source = "generated by tools/make_trap_pdfs.py (original text, public domain)"\n'
        f'sha256 = "{sha}"\n'
        f"pages = [{checked}]\n"
        f"traps = {traps!r}\n".replace("'", '"')
        + f'notes = "{note}"\n',
        encoding="utf-8",
    )


def trap_book() -> None:
    book_id = "trap-lantern"
    folder = CORPUS / book_id
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "book.pdf"
    book = Book(pdf, "The Lantern Keeper")

    # Front matter on page 1: title and a short preface.
    book.headers = False
    book.heading("The Lantern Keeper", 22)
    book.heading("PREFACE", 14)
    text = (
        "This short book was written to test how PageVoice cleans up a PDF. Every trap a "
        "real book can set is here somewhere: running heads, page numbers, notes at the "
        "foot of the page, words split at the end of a line, and more."
    )
    book.paragraph(para(text), indent=False, expected=text)

    book.headers = True
    book.chapter("CHAPTER I", "The Tower")
    # Drop cap and small caps.
    first = para(
        ("dc", "T"),
        ("w", "he"),
        ("sc", "TOWER"),
        ("sc", "STOOD"),
        "on a ledge of black rock, a well-known mark for every sailor on the coast, and "
        "it had stood there longer than anyone could remember.",
    )
    book.paragraph(
        first,
        indent=False,
        expected="The Tower Stood on a ledge of black rock, a well-known mark for every "
        "sailor on the coast, and it had stood there longer than anyone could remember.",
    )
    # Footnote markers, ligatures and a soft hyphen.
    text = "Its keeper was a quiet man who kept a ﬁne garden of ﬂowers in the lee of the wall"
    note1 = "1 Sea pinks and thrift, mostly, which grow where nothing else will."
    tail = "and who spoke to the gulls more than to people, which suited him."
    book.paragraph(
        para(text, ("sup", "1", note1), tail),
        expected="Its keeper was a quiet man who kept a fine garden of flowers in the lee of "
        "the wall and who spoke to the gulls more than to people, which suited him.",
    )
    text = "He had come to the light as a boy, and the work had become as natural to him as breathing; he could not imagine a life without the lamp."  # noqa: E501
    book.paragraph(para(text), expected=text)
    # Line-break hyphens: "extra-ordinary" must be rejoined (the joined form appears
    # elsewhere), "self-taught" must keep its hyphen (the hyphenated form appears
    # elsewhere).
    p = para(
        "The keeper was self-taught in most things, and he had read every book the boat had "
        "ever brought him, from sermons to an extraordinary atlas of the stars, though the",
        ("brk", "extraordinary", 5),
        "volume of",
        ("brk", "self-taught", 5),
        "seamanship had been his favourite since boyhood.",
    )
    book.paragraph(
        p,
        expected="The keeper was self-taught in most things, and he had read every book the "
        "boat had ever brought him, from sermons to an extraordinary atlas of the stars, "
        "though the extraordinary volume of self-taught seamanship had been his favourite "
        "since boyhood.",
    )
    book.caption("Figure 1. The lantern room at dusk.")
    soft = "watch­man"
    text = f"Each night he was the only {soft} on that stretch of coast."
    book.paragraph(
        para(text), expected="Each night he was the only watchman on that stretch of coast."
    )
    for sentence in FILLER * 2:
        book.paragraph(para(sentence), expected=sentence)
    # A paragraph long enough to run over a page break.
    long = " ".join(FILLER)
    book.paragraph(para(long), expected=long)
    note2 = "2 The log survives, though the early pages are hard to read."
    text = "He kept the log in a careful hand"
    tail = "and never missed a day."
    book.paragraph(
        para(text, ("sup", "2", note2), tail),
        expected="He kept the log in a careful hand and never missed a day.",
    )

    for sentence in FILLER * 3:  # enough pages for running heads to repeat
        book.paragraph(para(sentence), expected=sentence)

    book.chapter("CHAPTER II", "The Storm")
    for sentence in list(reversed(FILLER)) * 3:
        book.paragraph(para(sentence), expected=sentence)
    text = "When the storm came at last it came from the west, as the old men had said it would."  # noqa: E501
    book.paragraph(para(text), expected=text)
    for sentence in FILLER * 4:
        book.paragraph(para(sentence), expected=sentence)
    book.close()
    write_candidates(book_id, book)
    write_toml(
        book_id,
        pdf,
        [
            "running heads that change per chapter",
            "page numbers",
            "footnotes",
            "line-break hyphens (real and not)",
            "ligatures",
            "soft hyphen",
            "drop cap",
            "small caps",
            "paragraph across a page break",
            "caption",
        ],
        book.page,
        "Small caps are expected in normal case; the drop cap joins its word.",
    )


def two_column() -> None:
    book_id = "trap-two-column"
    folder = CORPUS / book_id
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "book.pdf"
    c = Canvas(str(pdf), pagesize=letter, invariant=1)
    c.setTitle("Two Columns")
    y = H - MARGIN
    lines = wrap_plain(" ".join(FILLER), BODY)
    c.setFont("Vera", BODY)
    for line in lines:
        y -= LEADING
        c.drawString(MARGIN, y, line)
    c.showPage()
    column = (TEXT_W - 24) / 2
    text = " ".join(FILLER * 2).split()
    col_lines, line = [], ""
    for word in text:
        trial = f"{line} {word}".strip()
        if width(trial) > column and line:
            col_lines.append(line)
            line = word
        else:
            line = trial
    col_lines.append(line)
    half = (len(col_lines) + 1) // 2
    c.setFont("Vera", BODY)
    for index, line in enumerate(col_lines):
        x = MARGIN if index < half else MARGIN + column + 24
        row = index if index < half else index - half
        c.drawString(x, H - MARGIN - LEADING * (row + 1), line)
    c.showPage()
    c.save()
    folder.joinpath("candidate").mkdir(exist_ok=True)
    (folder / "candidate" / "page-001.txt").write_text(" ".join(FILLER) + "\n", encoding="utf-8")
    (folder / "candidate" / "page-002.txt").write_text("", encoding="utf-8")
    write_toml(
        book_id,
        pdf,
        ["two-column page (must be flagged, not read)"],
        2,
        "Page 2 has two columns: it is flagged and its text kept as a removal, so it reads as empty.",  # noqa: E501
    )


def _noise_png(seed: int) -> bytes:
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    image = Image.new("L", (850, 1100), 255)
    draw = ImageDraw.Draw(image)
    for row in range(60, 1040, 22):
        x = 80
        while x < 760:
            length = rng.randint(15, 60)
            draw.rectangle([x, row, x + length, row + 9], fill=40)
            x += length + rng.randint(8, 14)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def scanned() -> None:
    from reportlab.lib.utils import ImageReader

    for book_id, text_pages in (("trap-scanned-page", True), ("trap-scanned", False)):
        folder = CORPUS / book_id
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder / "book.pdf"
        c = Canvas(str(pdf), pagesize=letter, invariant=1)
        c.setTitle("Scanned")
        if text_pages:
            c.setFont("Vera", BODY)
            y = H - MARGIN
            for line in wrap_plain(FILLER[0], BODY):
                y -= LEADING
                c.drawString(MARGIN, y, line)
            c.showPage()
        for seed in (1, 2):
            c.drawImage(ImageReader(io.BytesIO(_noise_png(seed))), 0, 0, W, H)
            c.showPage()
        c.save()
        cand = folder / "candidate"
        cand.mkdir(exist_ok=True)
        if text_pages:
            (cand / "page-001.txt").write_text(FILLER[0] + "\n", encoding="utf-8")
            (cand / "page-002.txt").write_text("", encoding="utf-8")
            (cand / "page-003.txt").write_text("", encoding="utf-8")
        note = (
            "Pages 2-3 are pictures with no text: flagged as scanned."
            if text_pages
            else "No text layer at all: PageVoice must refuse it with a plain OCR message."
        )
        write_toml(book_id, pdf, ["scanned page(s), no text layer"], 3 if text_pages else 2, note)


def bookmarks() -> None:
    book_id = "trap-bookmarks"
    folder = CORPUS / book_id
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "book.pdf"
    book = Book(pdf, "Harbour Tales")
    book.headers = False
    c = book.canvas
    for number, title in enumerate(["The Harbour", "The Crossing", "Home Again"], 1):
        if number > 1:
            book.new_page(chapter_start=True)
        key = f"ch{number}"
        c.bookmarkPage(key)
        c.addOutlineEntry(title, key, level=0)
        book.heading(title, 14)
        for sentence in FILLER[number - 1 : number + 2]:
            book.paragraph(para(sentence), expected=sentence)
    book.close()
    write_candidates(book_id, book)
    write_toml(
        book_id,
        pdf,
        ["chapters from bookmarks; headings have no Chapter N pattern"],
        book.page,
        "Three top-level bookmarks give three chapters.",
    )


def word_export() -> None:
    """Like a Word export: every word drawn on its own, lines drawn out of reading order."""
    book_id = "trap-word-export"
    folder = CORPUS / book_id
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "book.pdf"
    c = Canvas(str(pdf), pagesize=letter, invariant=1)
    c.setTitle("Word Export")
    rng = random.Random(7)
    wanted: dict[int, list[str]] = {}
    paragraphs = FILLER[:3]
    for page in (1, 2):
        rows = []
        y = H - MARGIN
        for text in paragraphs:
            lines = wrap_plain(text, BODY)
            for index, line in enumerate(lines):
                y -= LEADING
                x = MARGIN + (INDENT if index == 0 else 0)
                rows.append((x, y, line))
            y -= 6
        rng.shuffle(rows)  # drawn in no particular order
        c.setFont("Vera", BODY)
        for x, y, line in rows:
            for word in line.split():
                c.drawString(x, y, word)
                x += width(word + " ")
        c.setFont("Vera", 9)
        c.drawCentredString(W / 2, 36, str(page))
        c.showPage()
        wanted[page] = list(paragraphs)
    c.save()
    cand = folder / "candidate"
    cand.mkdir(exist_ok=True)
    for page, lines in wanted.items():
        (cand / f"page-{page:03d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_toml(
        book_id,
        pdf,
        ["each word drawn separately", "lines out of order"],
        2,
        "Reading order comes from positions, not drawing order.",
    )


def main() -> int:
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    trap_book()
    two_column()
    scanned()
    bookmarks()
    word_export()
    for folder in sorted(CORPUS.glob("trap-*")):
        print(folder.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
