"""Shared helpers for the golden corpus: find books, and render a page the README way.

Format (tests/corpus/README.md): one paragraph per line in reading order; a paragraph
that runs over a page break belongs to the page where it starts; removed text is left
out; notes go under a line "[notes]".

For PDFs a "page" is a PDF page. For EPUB and TXT, book.toml says `unit = "chapter"`
and page-NNN.txt is chapter NNN (1-based).
"""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pagevoice.document import Book, Paragraph

CORPUS = Path(__file__).resolve().parent
DOWNLOADS = CORPUS / ".downloads"


@dataclass
class CorpusBook:
    id: str
    folder: Path
    meta: dict

    @property
    def unit(self) -> str:
        return self.meta.get("unit", "page")

    @property
    def path(self) -> Path:
        name = self.meta.get("file", "book." + self.meta["format"])
        local = self.folder / name
        if local.exists():
            return local
        return DOWNLOADS / self.id / name

    def available(self) -> bool:
        path = self.path
        if not path.exists():
            return False
        expected = self.meta.get("sha256")
        return not expected or hashlib.sha256(path.read_bytes()).hexdigest() == expected

    def golden_pages(self, kind: str = "expected") -> dict[int, Path]:
        folder = self.folder / kind
        return {int(p.stem.split("-")[1]): p for p in sorted(folder.glob("page-*.txt"))}


def books() -> list[CorpusBook]:
    out = []
    for toml in sorted(CORPUS.glob("*/*/book.toml")):
        meta = tomllib.loads(toml.read_text(encoding="utf-8"))
        out.append(CorpusBook(meta.get("id", toml.parent.name), toml.parent, meta))
    return out


def _page(paragraph: Paragraph) -> int | None:
    for span in paragraph.spans:
        if not span.removed and span.text.strip() and span.location.page:
            return span.location.page
    return None


def render_page(book: Book, number: int, unit: str = "page") -> str:
    """The text of one page (or chapter) in the golden format."""
    lines: list[str] = []
    notes: list[str] = []
    if unit == "chapter":
        if number > len(book.chapters):
            return ""
        chapter = book.chapters[number - 1]
        lines = [p.text for p in chapter.paragraphs if p.text]
        notes = [p.text for p in chapter.notes if p.text]
    else:
        for chapter in book.chapters:
            lines += [p.text for p in chapter.paragraphs if p.text and _page(p) == number]
            notes += [p.text for p in chapter.notes if p.text and _page(p) == number]
    if notes:
        lines += ["[notes]", *notes]
    return "\n".join(lines)


def normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())
