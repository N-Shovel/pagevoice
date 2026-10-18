"""EPUB, parsed by hand (D5: no EbookLib). An EPUB is a zip of XHTML plus an OPF manifest.

Each spine document becomes a chapter, split further where the table of contents points
at an anchor inside it. Footnotes and endnotes are moved to the end of the chapter that
references them (D11), their markers kept as removals. Tables and figure captions are kept
as removals too. DRM-protected books are refused, never decrypted.
"""

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from pagevoice.cleanup.language import book_language, rules_for
from pagevoice.cleanup.text import fix_characters
from pagevoice.document import Book, Chapter, IngestError, Location, Paragraph, Reason, Span

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
# Font obfuscation (IDPF, Adobe) is allowed; any other encryption is DRM.
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
DRM_MESSAGE = (
    "This book is protected with DRM, so PageVoice can't read it. PageVoice never removes "
    "DRM. If you have a DRM-free copy, open that instead."
)

BLOCK = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dt", "dd",
    "tr", "td", "th", "figcaption", "caption", "section", "article", "aside", "header",
    "footer", "table", "figure", "ol", "ul", "dl", "body", "nav", "hr",
}  # fmt: skip
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP = {"head", "script", "style"}  # never book text (the page <title> is in <head>)
FIGURES = {"svg", "math"}  # their text is kept, as FIGURE removals
NOTE_TYPES = ("footnote", "endnote", "rearnote", "note")  # whole words: not "endnotes"
DOC_NOTE_ROLES = {"doc-footnote", "doc-endnote"}
# Project Gutenberg's licence header/footer, and publishers' imprint pages.
BOILERPLATE_IDS = {"pg-header", "pg-footer", "pg-machine-header", "pg-start-separator"}
BOILERPLATE_TYPES = ("imprint", "colophon", "copyright-page")
_SPACE = re.compile(r"\s+")
_MARKER = re.compile(r"[0-9a-zA-Z*†‡§¶#]+")  # what a note reference's text looks like
_LINK = -1.0  # temporary marker on spans inside internal links (cleared on flush)


@dataclass
class Block:
    spans: list[Span]
    kind: str  # text, heading, note
    ids: list[str] = field(default_factory=list)
    note_id: str | None = None  # set when the block belongs to a footnote/endnote
    refs: list[str] = field(default_factory=list)  # hrefs of note references in it


def _internal(attrs: dict[str, str | None]) -> bool:
    href = attrs.get("href") or ""
    return bool(href) and "://" not in href


def _types(attrs: dict[str, str | None]) -> str:
    return f"{attrs.get('epub:type') or ''} {attrs.get('role') or ''}".lower()


class _Extractor(HTMLParser):
    """Turn one XHTML document into blocks of spans."""

    def __init__(self, part: str) -> None:
        super().__init__(convert_charrefs=True)
        self.part = part
        self.blocks: list[Block] = []
        self.stack: list[tuple[str, dict]] = []
        self.spans: list[Span] = []
        self.pending_ids: list[str] = []
        self.skip = 0
        self.noteref = 0  # inside a note reference or backlink
        self.refs: list[str] = []

    def _context(self) -> tuple[str, str | None]:
        """Block kind and note id, from the open-element stack."""
        kind, note_id = "text", None
        for tag, info in self.stack:
            if info.get("note"):
                kind, note_id = "note", info.get("note_id") or note_id
            if tag in HEADINGS and kind != "note":
                kind = "heading"
        return kind, note_id

    def _reason(self) -> Reason | None:
        """Why text at this point won't be read, if it won't."""
        if self.noteref:
            return Reason.FOOTNOTE_MARKER
        reason = None
        for _, info in self.stack:
            reason = info.get("reason") or reason
        return reason

    def _flush(self) -> None:
        text = "".join(s.text for s in self.spans)
        linked = sum(len(s.text.strip()) for s in self.spans if s.location.top == _LINK)
        if text.strip() and linked >= 0.6 * len(text.strip()):
            # A table of contents: links to the book's own pages. Kept, not read.
            for span in self.spans:
                if span.reason is None:
                    span.reason = Reason.CONTENTS
        for span in self.spans:
            if span.location.top == _LINK:
                span.location.top = None
        if text.strip():
            kind, note_id = self._context()
            block = Block(self.spans, kind, self.pending_ids, note_id, self.refs)
            self.blocks.append(block)
            self.pending_ids = []
            self.refs = []
        self.spans = []

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "br":
            self._text(" ")
            return
        info: dict = {}
        types = _types(attrs)
        classes = (attrs.get("class") or "").lower()
        words = set(types.split())
        if attrs.get("id"):
            self.pending_ids.append(attrs["id"])
            info["id"] = attrs["id"]
            note = self._open_note()
            if note is not None and not note.get("note_id"):
                note["note_id"] = attrs["id"]  # <aside epub:type="footnote"><p id="fn1">
        if words & set(NOTE_TYPES) or words & DOC_NOTE_ROLES or "footnote" in classes.split():
            info["note"] = True
            info["note_id"] = attrs.get("id")
        if tag == "table":
            info["reason"] = Reason.TABLE
        elif tag in ("figcaption", "caption") or "caption" in classes.split():
            info["reason"] = Reason.CAPTION
        if (
            attrs.get("id") in BOILERPLATE_IDS
            or "pg-boilerplate" in classes.split()
            or any(t in types for t in BOILERPLATE_TYPES)
        ):
            info["reason"] = Reason.BOILERPLATE
        if tag in FIGURES:
            info["reason"] = Reason.FIGURE
            if attrs.get("alttext"):  # MathML's spoken-form hint
                self.stack.append((tag, info))
                self._text(attrs["alttext"] + " ")
                self.stack.pop()
        in_note = self._open_note() is not None
        if tag == "a" and (
            "noteref" in types or "fnanchor" in classes.split() or self._looks_like_noteref(attrs)
        ):
            self.noteref += 1
            info["noteref"] = True
            self.refs.append(attrs.get("href") or "")
        elif tag == "a" and ("backlink" in types or (in_note and _internal(attrs))):
            # The "return to text" arrow or label inside a note
            self.noteref += 1
            info["noteref"] = True
        elif tag == "a" and attrs.get("href") and "://" not in attrs["href"]:
            info["link"] = True
            if "#" in attrs["href"] and not in_note:
                # <a href="#fn1"><sup>1</sup></a>: a note reference written the other way
                # round. Decided at </a>, once its text is known.
                info.update(maybe_ref=attrs["href"], first_span=len(self.spans))
        if tag == "sup":
            for _, outer in reversed(self.stack):
                if outer.get("maybe_ref"):
                    outer["has_sup"] = True
                    break
        if tag in BLOCK:
            self._flush()
        if tag == "img":
            alt = (attrs.get("alt") or "").strip()
            if len(alt) == 1 and alt.isalpha():
                self._text(alt)  # a drop cap drawn as a picture of its letter
            elif alt and any(tag in HEADINGS for tag, _ in self.stack):
                self._text(alt)  # a heading drawn as a picture ("Chapter IV")
            elif alt:
                self.stack.append((tag, {"reason": Reason.FIGURE}))
                self._text(alt)  # a picture's description: kept, not read
                self.stack.pop()
            return
        if tag == "hr":
            return
        self.stack.append((tag, info))

    def _open_note(self) -> dict | None:
        return next((info for _, info in reversed(self.stack) if info.get("note")), None)

    def _looks_like_noteref(self, attrs: dict) -> bool:
        # <sup><a href="#fn1">1</a></sup> without epub:type
        return bool(self.stack and self.stack[-1][0] == "sup" and "#" in (attrs.get("href") or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        # pop up to and including the matching tag (tolerates sloppy markup)
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                if tag in BLOCK:
                    self._flush()
                for _, info in self.stack[index:]:
                    if info.get("noteref"):
                        self.noteref -= 1
                    if info.get("maybe_ref") and info.get("has_sup"):
                        self._late_noteref(info)
                del self.stack[index:]
                break

    def _late_noteref(self, info: dict) -> None:
        """An internal link that holds only a superscript marker ("1", "*", "†") is a
        note reference: its text becomes a footnote_marker removal, like <sup><a>."""
        spans = self.spans[info["first_span"] :]
        text = "".join(s.text for s in spans).strip()
        if not text or len(text) > 4 or not _MARKER.fullmatch(text):
            return
        for span in spans:
            if span.reason is None:
                span.reason = Reason.FOOTNOTE_MARKER
            span.location.top = None
        self.refs.append(info["maybe_ref"])

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self._text(data)

    def _text(self, data: str) -> None:
        data = _SPACE.sub(" ", fix_characters(data))
        if not data:
            return
        in_link = any(info.get("link") for _, info in self.stack)
        location = Location(part=self.part, top=_LINK if in_link else None)
        self.spans.append(Span(data, self._reason(), location))

    def close(self) -> None:
        super().close()
        self._flush()


def _tidy(spans: list[Span]) -> list[Span]:
    """Trim outer whitespace and collapse spaces left where markers were removed."""
    if not spans:
        return spans
    spans[0].text = spans[0].text.lstrip()
    spans[-1].text = spans[-1].text.rstrip()
    return [s for s in spans if s.text]


class _Epub:
    def __init__(self, path: Path) -> None:
        try:
            self.zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise IngestError("This EPUB file is damaged or isn't really an EPUB.") from exc
        self.names = set(self.zip.namelist())

    def read(self, name: str) -> bytes:
        try:
            return self.zip.read(name)
        except KeyError as exc:
            raise IngestError(f"This EPUB is missing a file it needs ({name}).") from exc

    def xml(self, name: str) -> ElementTree.Element:
        try:
            return ElementTree.fromstring(self.read(name))
        except ElementTree.ParseError as exc:
            raise IngestError(f"This EPUB has a damaged file ({name}).") from exc

    def check_drm(self) -> None:
        if "META-INF/rights.xml" in self.names:
            raise IngestError(DRM_MESSAGE)
        if "META-INF/encryption.xml" not in self.names:
            return
        root = self.xml("META-INF/encryption.xml")
        for method in root.iter():
            if (
                method.tag.endswith("EncryptionMethod")
                and method.get("Algorithm") not in FONT_OBFUSCATION
            ):
                raise IngestError(DRM_MESSAGE)


def _href_key(base: str, href: str) -> tuple[str, str]:
    """Resolve an href against a document path: (path in zip, fragment)."""
    href = unquote(href)
    path, _, fragment = href.partition("#")
    full = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    return full, fragment


def _toc(epub: _Epub, opf_path: str, manifest: dict, spine_toc: str | None) -> list:
    """Top-level table-of-contents entries as (path, fragment, title), in order."""
    nav = next((m for m in manifest.values() if "nav" in m["properties"].split()), None)
    entries = []
    if nav:
        root = epub.xml(nav["path"])
        for element in root.iter():
            if element.tag.endswith("nav") and "toc" in (
                element.get("{http://www.idpf.org/2007/ops}type") or element.get("role") or ""
            ):
                top = next((c for c in element if c.tag.endswith("ol")), None)
                for li in top if top is not None else []:
                    link = next((a for a in li.iter() if a.tag.endswith("a")), None)
                    if link is not None and link.get("href"):
                        title = _SPACE.sub(" ", "".join(link.itertext())).strip()
                        entries.append((*_href_key(nav["path"], link.get("href")), title))
                break
    if not entries and spine_toc and spine_toc in manifest:
        ncx_path = manifest[spine_toc]["path"]
        root = epub.xml(ncx_path)
        nav_map = root.find("ncx:navMap", NS)
        for point in nav_map.findall("ncx:navPoint", NS) if nav_map is not None else []:
            label = point.find("ncx:navLabel/ncx:text", NS)
            content = point.find("ncx:content", NS)
            if content is not None and content.get("src"):
                title = (label.text or "").strip() if label is not None else ""
                entries.append((*_href_key(ncx_path, content.get("src")), title))
    return entries


def read_epub(path: Path, *, language: str | None = None) -> Book:
    epub = _Epub(path)
    epub.check_drm()
    container = epub.xml("META-INF/container.xml")
    rootfile = container.find(".//c:rootfile", NS)
    if rootfile is None:
        raise IngestError("This EPUB has no package file, so PageVoice can't read it.")
    opf_path = rootfile.get("full-path", "")
    opf = epub.xml(opf_path)

    metadata = opf.find("opf:metadata", NS)

    def meta(tag: str) -> str:
        element = metadata.find(f"dc:{tag}", NS) if metadata is not None else None
        return _SPACE.sub(" ", element.text or "").strip() if element is not None else ""

    book = Book(
        title=meta("title") or path.stem,
        author=meta("creator"),
        language=book_language(meta("language"), language),
        source_format="epub",
    )
    rules = rules_for(book.language)

    manifest = {}
    manifest_element = opf.find("opf:manifest", NS)
    for item in manifest_element if manifest_element is not None else []:
        manifest[item.get("id")] = {
            "path": _href_key(opf_path, item.get("href", ""))[0],
            "type": item.get("media-type", ""),
            "properties": item.get("properties", ""),
        }
    _read_cover(epub, opf, manifest, book)

    spine = opf.find("opf:spine", NS)
    if spine is None:
        raise IngestError("This EPUB has no reading order, so PageVoice can't read it.")
    # Every spine document is read. Ones outside the reading order (linear="no": pop-up
    # notes, answer keys) supply notes, and the rest of their text is kept as removals.
    spine_parts = [
        (manifest[ref.get("idref")]["path"], ref.get("linear", "yes") != "no")
        for ref in spine
        if ref.get("idref") in manifest
    ]
    order = [part for part, linear in spine_parts if linear]
    extra = [part for part, linear in spine_parts if not linear]
    toc = _toc(epub, opf_path, manifest, spine.get("toc"))
    starts: dict[tuple[str, str], str] = {(p, f): t for p, f, t in toc}

    # Parse every document first, so notes in another file (endnotes.xhtml) can be found.
    documents: dict[str, list[Block]] = {}
    notes: dict[tuple[str, str], list[Block]] = {}
    for part in order + extra:
        parser = _Extractor(part)
        parser.feed(epub.read(part).decode("utf-8", errors="replace"))
        parser.close()
        documents[part] = parser.blocks
        for number, block in enumerate(parser.blocks):
            if block.kind == "note":
                block.note_id = block.note_id or f"#unnamed-{number}"
                notes.setdefault((part, block.note_id), []).append(block)

    chapters: list[Chapter] = []
    moved: set[tuple[str, str]] = set()
    titled: set[int] = set()  # chapters already named by a heading in the text
    pending: list[tuple[Chapter, tuple[str, str], Block]] = []  # notes not yet cited
    for part in order:
        current: Chapter | None = None
        title = starts.get((part, ""))
        for block in documents[part]:
            split_title = next((starts[(part, i)] for i in block.ids if (part, i) in starts), None)
            if current is None or split_title:
                current = Chapter(title=split_title or title or "")
                chapters.append(current)
            if block.kind == "note":
                key = (part, block.note_id)
                if key not in moved:  # cited later, or never: decided after the loop
                    pending.append((current, key, block))
                continue
            paragraph = _paragraph(block)
            current.paragraphs.append(paragraph)
            if block.kind == "heading" and id(current) not in titled and paragraph.text:
                current.title = paragraph.text
                titled.add(id(current))
            for href in block.refs:
                target = _href_key(part, href)
                if target in notes and target not in moved:
                    moved.add(target)
                    current.notes += [_paragraph(b, kind="note") for b in notes[target]]
    # A note nobody cites stays with its own chapter, at the end, never inline (D11).
    for chapter, key, block in pending:
        if key not in moved:
            chapter.notes.append(_paragraph(block, kind="note"))
    # Text outside the reading order: kept, not read. Notes cited from it were moved.
    outside: list[Paragraph] = []
    for part in extra:
        for block in documents[part]:
            if block.kind == "note" and (part, block.note_id) in moved:
                continue
            paragraph = _paragraph(block)
            for span in paragraph.spans:
                span.reason = span.reason or Reason.NON_LINEAR
            outside.append(paragraph)

    kept: list[Chapter] = []
    carry: list[Paragraph] = []  # removals from text-less sections, kept for review
    for number, chapter in enumerate(chapters, 1):
        if not any(p.text for p in chapter.paragraphs) and not chapter.notes:
            (kept[-1].paragraphs if kept else carry).extend(chapter.paragraphs)
            continue
        if not chapter.title:
            chapter.title = rules.SECTION_TITLE.format(n=number)
        chapter.paragraphs[:0] = carry
        carry = []
        kept.append(chapter)
    book.chapters = kept or [Chapter(title=book.title, paragraphs=carry)]
    book.chapters[-1].paragraphs += outside
    return book


def _paragraph(block: Block, kind: str | None = None) -> Paragraph:
    spans = _tidy([Span(s.text, s.reason, s.location) for s in block.spans])
    return Paragraph(spans, kind=kind or block.kind)


def _read_cover(epub: _Epub, opf: ElementTree.Element, manifest: dict, book: Book) -> None:
    cover = next((m for m in manifest.values() if "cover-image" in m["properties"]), None)
    if cover is None:
        metadata = opf.find("opf:metadata", NS)
        for element in metadata if metadata is not None else []:
            if element.get("name") == "cover" and element.get("content") in manifest:
                cover = manifest[element.get("content")]
    if cover and cover["path"] in epub.names and cover["type"].startswith("image/"):
        book.cover = epub.read(cover["path"])
        book.cover_type = cover["type"]
