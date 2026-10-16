"""The book as PageVoice holds it: chapters of paragraphs, each a list of spans.

Nothing is deleted silently (CLAUDE.md rule 2). Text that won't be read keeps its place as
a removed span with a reason and a location, so the review screen can show it dimmed and
the user can restore it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Reason(StrEnum):
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    FOOTNOTE = "footnote"  # a note, when the "drop notes" setting is on
    FOOTNOTE_MARKER = "footnote_marker"
    CAPTION = "caption"
    TABLE = "table"
    CONTENTS = "contents"  # a table of contents
    BOILERPLATE = "boilerplate"  # e.g. Project Gutenberg licence header and footer
    HYPHEN = "hyphen"  # a line-break hyphen taken out when a word was rejoined
    MULTI_COLUMN = "multi_column"  # page flagged; its text isn't read until the user says so
    NO_TEXT = "no_text"  # scanned page with no text layer


@dataclass
class Location:
    page: int | None = None  # 1-based page number in the source (PDF), if any
    top: float | None = None  # distance from the top of the page, in points
    part: str | None = None  # file inside an EPUB, if any


@dataclass
class Span:
    text: str
    reason: Reason | None = None
    location: Location = field(default_factory=Location)
    restored: bool = False  # the user brought a removed span back

    @property
    def removed(self) -> bool:
        return self.reason is not None and not self.restored


@dataclass
class Paragraph:
    spans: list[Span]
    kind: str = "text"  # text, heading or note

    @property
    def text(self) -> str:
        """What gets read aloud."""
        return "".join(s.text for s in self.spans if not s.removed).strip()

    @property
    def original(self) -> str:
        return "".join(s.text for s in self.spans).strip()

    @property
    def removals(self) -> list[Span]:
        return [s for s in self.spans if s.reason is not None]

    @classmethod
    def plain(cls, text: str, location: Location | None = None, kind: str = "text") -> Paragraph:
        return cls([Span(text, location=location or Location())], kind=kind)

    @classmethod
    def removed(cls, text: str, reason: Reason, location: Location | None = None) -> Paragraph:
        return cls([Span(text, reason, location or Location())])


@dataclass
class Chapter:
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    notes: list[Paragraph] = field(default_factory=list)  # footnotes, read at the end
    start_page: int | None = None

    def readable(self, *, drop_notes: bool = False) -> list[str]:
        """The paragraphs to read, in order: title, body, then notes (D11)."""
        out = [p.text for p in self.paragraphs if p.text]
        if not drop_notes:
            out += [p.text for p in self.notes if p.text]
        return out


@dataclass
class PageFlag:
    page: int
    kind: str  # "scanned" or "multi_column"
    message: str


@dataclass
class Book:
    title: str
    language: str = "en"
    author: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    flags: list[PageFlag] = field(default_factory=list)
    cover: bytes | None = None
    cover_type: str | None = None  # MIME type
    source_format: str = ""  # txt, epub or pdf

    @property
    def removals(self) -> list[Span]:
        out = []
        for chapter in self.chapters:
            for paragraph in [*chapter.paragraphs, *chapter.notes]:
                out += paragraph.removals
        return out


class IngestError(RuntimeError):
    """A file PageVoice can't read. The message is plain language for the user."""
