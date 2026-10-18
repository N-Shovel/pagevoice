"""PDF layout cleanup: turn extracted lines into chapters of paragraphs with removals.

Rules (SPEC §4, .claude/rules/cleanup.md):
- Headers and footers: lines in the top or bottom strip that repeat on many pages, or that
  sit in the same isolated slot on most pages (running heads that change per chapter).
- Page numbers: lone numbers (Arabic or Roman) in those strips.
- Footnotes: a run of smaller text at the bottom of a page. Markers are taken out of the
  sentences; the notes move to the end of the chapter (D11).
- Captions ("Figure 3.") and ruled tables are kept as removals.
- Scanned pages and multi-column pages are flagged; multi-column text is kept as a removal
  so garbled column-interleaved text is never read (D14).
- Drop caps, small caps, ligatures and soft hyphens are repaired; split words are rejoined
  only with evidence (D12).
- Chapters: top-level bookmarks first; otherwise a larger font together with a chapter
  pattern (D13).
"""

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from pagevoice.cleanup.chapters import finish_chapters
from pagevoice.cleanup.language import book_language, rules_for
from pagevoice.cleanup.text import should_rejoin, word_counts
from pagevoice.document import Book, Chapter, Location, PageFlag, Paragraph, Reason, Span
from pagevoice.ingest.pdf import Extracted, Line, Page

STRIP = 0.2  # running heads and footers sit in the top or bottom fifth of the page
_ROMAN = re.compile(r"^[ivxlcdm]+$", re.I)
_PAGE_NUMBER = re.compile(r"^[-–—(\[]?\s*(\d{1,4}|[ivxlcdm]{1,8})\s*[-–—)\]]?$", re.I)
# "12 THE WISDOM OF LIFE" or "DIVISION OF THE SUBJECT 5"
_NUMBERED_HEAD = re.compile(
    r"^(\d{1,4}|[ivxlc]{1,6})\s+\D.*$|^.*\D\s+(\d{1,4}|[ivxlc]{1,6})$", re.I
)
_MARKER = re.compile(r"^[\d*†‡§¶]{1,3}[.)]?$")
_NOTE_START = re.compile(r"^[\d*†‡§¶]{1,3}[.)]?\s")
_SMALL_CAPS_FONT = re.compile(r"smallcaps|small-caps|[-+,]sc\b|caps", re.I)
_SENTENCE_END = re.compile(r"[.!?:;\"”’)\]]$")
_HYPHENS = "-‐‑"
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")

MULTI_COLUMN_MESSAGE = (
    "This page has two or more columns. PageVoice can't read columns in the right order "
    "yet, so it skips this page. Restore it in review if it reads fine."
)
SCANNED_PAGE_MESSAGE = "This page is a picture with no text (a scan). It needs OCR to be read."


@dataclass
class Role:
    reason: Reason | None = None  # None: body text
    note: bool = False  # part of a footnote block


@dataclass
class Layout:
    body_size: float
    line_gap: float
    roles: dict[int, Role] = field(default_factory=dict)  # id(line) -> role
    multi_column: set[int] = field(default_factory=set)  # page numbers


def _normal(text: str) -> str:
    words = [("#" if w.isdigit() or _ROMAN.match(w) else w) for w in text.lower().split()]
    return " ".join(words)


def _body_size(pages: list[Page]) -> float:
    weights: Counter[float] = Counter()
    for page in pages:
        for line in page.lines:
            for word in line.words:
                weights[round(word.size, 1)] += len(word.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _line_gap(pages: list[Page], body: float) -> float:
    gaps = []
    for page in pages:
        lines = [ln for ln in page.lines if abs(ln.size - body) < 0.6]
        for a, b in zip(lines, lines[1:], strict=False):
            gap = b.top - a.top
            if 0.8 * body < gap < 2.5 * body:
                gaps.append(gap)
    return statistics.median(gaps) if gaps else body * 1.2


def _edge_lines(page: Page, top: bool) -> list[Line]:
    """The two lines nearest the top or bottom edge, if they're in the outer strip."""
    if top:
        return [ln for ln in page.lines[:2] if ln.top < STRIP * page.height]
    return [ln for ln in page.lines[-2:] if ln.bottom > (1 - STRIP) * page.height][::-1]


def _isolated(page: Page, line: Line, gap: float, top: bool) -> bool:
    """True if an edge line stands apart from the text next to it."""
    lines = page.lines
    index = lines.index(line)
    neighbour_index = index + 1 if top else index - 1
    if not 0 <= neighbour_index < len(lines):
        return True
    neighbour = lines[neighbour_index]
    distance = neighbour.top - line.top if top else line.top - neighbour.top
    return distance > 1.4 * gap


def _slot(page: Page, line: Line) -> int:
    return round(200 * line.top / page.height)  # half-percent steps of the page height


def _find_headers_footers(pages: list[Page], layout: Layout, rules) -> None:
    """Running heads, footers and page numbers at the top and bottom of pages.

    Looking from the edge inwards, a line is taken out if it is a lone page number; a
    title with a page number at one end, standing apart from the text, at the top ("4 THE
    WISDOM OF LIFE"; at the bottom that shape is usually a footnote); text that repeats
    on many pages; or a line standing apart in the same slot as on most pages (running
    heads that change per chapter). The first line that is none of
    these stops the search, so body text is never taken.
    """
    text_pages = [p for p in pages if p.lines]
    # A lone number on the edge line is a page number, however short the document.
    for page in text_pages:
        for top in (True, False):
            for line in _edge_lines(page, top)[:1]:
                small = line.size <= 1.05 * layout.body_size
                if small and _PAGE_NUMBER.match(line.text.strip()):
                    layout.roles[id(line)] = Role(Reason.PAGE_NUMBER)
    if len(text_pages) < 3:
        return
    for top, reason in ((True, Reason.HEADER), (False, Reason.FOOTER)):
        repeats: Counter[str] = Counter()
        slots: Counter[int] = Counter()
        for page in text_pages:
            repeats.update({_normal(line.text) for line in _edge_lines(page, top)})
            for line in _edge_lines(page, top):
                if _isolated(page, line, layout.line_gap, top):
                    slots[_slot(page, line)] += 1
        need = max(3, 0.4 * len(text_pages))
        slot_need = max(3, 0.5 * len(text_pages))
        for page in text_pages:
            for line in _edge_lines(page, top):
                text = line.text.strip()
                isolated = _isolated(page, line, layout.line_gap, top)
                if line.size > 1.05 * layout.body_size or rules.is_chapter_heading(text):
                    break  # a heading, not a running head or page number
                if _PAGE_NUMBER.match(text):
                    layout.roles[id(line)] = Role(Reason.PAGE_NUMBER)
                    continue
                slot = _slot(page, line)
                in_slot = any(slots[s] >= slot_need for s in (slot - 1, slot, slot + 1))
                if (
                    (top and isolated and _NUMBERED_HEAD.match(text))
                    or repeats[_normal(text)] >= need
                    or (in_slot and isolated)
                ):
                    layout.roles[id(line)] = Role(reason)
                    continue
                break


def _find_footnotes(page: Page, layout: Layout) -> None:
    """A run of small lines at the bottom of the page, starting with a marker or a rule."""
    lines = [ln for ln in page.lines if layout.roles.get(id(ln)) is None]
    run: list[Line] = []
    for line in reversed(lines):
        if line.size <= 0.9 * layout.body_size:
            run.insert(0, line)
        else:
            break
    if not run or run[0].top < 0.45 * page.height or len(run) == len(lines):
        return
    above = lines[len(lines) - len(run) - 1]
    has_rule = any(above.bottom - 1 <= y <= run[0].top + 1 for y in page.rules)
    if not (_NOTE_START.match(run[0].text + " ") or has_rule):
        return
    for line in run:
        layout.roles[id(line)] = Role(note=True)


def _in_table(line: Line, page: Page) -> bool:
    for x0, top, x1, bottom in page.tables:
        if (
            line.x0 >= x0 - 1
            and line.x1 <= x1 + 1
            and line.top >= top - 1
            and line.bottom <= bottom + 1
        ):
            return True
    return False


def _multi_column(page: Page, layout: Layout) -> bool:
    """True if a vertical channel of white space splits the page's text into columns.

    Looks in the middle half of the page for a strip at least 0.3 em wide that at most
    one line in ten crosses (prose never lines its spaces up like that), with a real share
    of the text on each side. Counting characters (not lines) keeps a contents page, whose
    right side is only page numbers, from counting.
    """
    body = [ln for ln in page.lines if layout.roles.get(id(ln)) is None]
    if len(body) < 8:
        return False
    step = min(0.5, layout.body_size / 10)
    lo, hi = 0.25 * page.width, 0.75 * page.width
    bins = int((hi - lo) / step)
    covered = [0] * bins
    for line in body:
        hit = [False] * bins
        for word in line.words:
            first = max(0, int((word.x0 - lo) / step))
            last = min(bins - 1, int((word.x1 - lo) / step))
            for b in range(first, last + 1):
                hit[b] = True
        for b, h in enumerate(hit):
            covered[b] += h
    limit = max(1, int(0.1 * len(body)))
    need = max(3, int(0.3 * layout.body_size / step))
    total = sum(len(w.text) for ln in body for w in ln.words)
    run = 0
    for b, count in enumerate(covered):
        run = run + 1 if count <= limit else 0
        if run >= need:
            x0 = lo + (b - run + 1) * step
            x1 = lo + (b + 1) * step
            left = sum(len(w.text) for ln in body for w in ln.words if w.x1 <= x0)
            right = sum(len(w.text) for ln in body for w in ln.words if w.x0 >= x1)
            if left >= 0.25 * total and right >= 0.25 * total:
                return True
    return False


def analyse(pages: list[Page], rules) -> Layout:
    body = _body_size(pages)
    layout = Layout(body_size=body, line_gap=_line_gap(pages, body))
    _find_headers_footers(pages, layout, rules)
    for page in pages:
        _find_footnotes(page, layout)
        for line in page.lines:
            if layout.roles.get(id(line)) is None and _in_table(line, page):
                layout.roles[id(line)] = Role(Reason.TABLE)
        if _multi_column(page, layout):
            layout.multi_column.add(page.number)
    return layout


# --- turning lines into spans -------------------------------------------------------


def _line_spans(line: Line, layout: Layout) -> list[Span]:
    """Spans for one line: text, with raised small markers as FOOTNOTE_MARKER removals."""
    size = line.size
    baseline = line.bottom
    location = Location(page=line.page, top=round(line.top, 1))
    spans: list[Span] = []
    words = list(line.words)
    for index, word in enumerate(words):
        text = word.text
        gap = " " if (spans and word.space_before) else ""
        is_marker = (
            _MARKER.match(text)
            and word.size <= 0.85 * size
            and word.bottom < baseline - 0.12 * size
            and index > 0
        )
        if is_marker:
            spans.append(Span(text, Reason.FOOTNOTE_MARKER, location))
            continue
        # Drop cap: a single big capital followed by the rest of its word ("T he").
        drop_cap = index == 0 and len(text) == 1 and text.isupper() and word.size >= 1.6 * size
        if drop_cap and len(words) > 1:
            words[1].space_before = False
        # Small caps: shrunken capitals. "I" + "T" -> "It", "MR." -> "Mr."
        letters = any(c.isalpha() for c in text)
        small = word.size <= 0.85 * size or bool(_SMALL_CAPS_FONT.search(word.font))
        if text.isupper() and letters and small and not drop_cap:
            joined = index > 0 and not word.space_before
            text = text.lower() if joined else text.capitalize()
        spans.append(Span(gap + text, location=location))
    return spans


def _text_of(spans: list[Span]) -> str:
    return "".join(s.text for s in spans if s.reason is None)


@dataclass
class _Builder:
    counts: Counter
    paragraphs: list[Paragraph] = field(default_factory=list)
    current: list[Span] = field(default_factory=list)
    current_kind: str = "text"
    pending: list[Paragraph] = field(default_factory=list)  # removals waiting for a break

    def close(self) -> None:
        if self.current:
            spans = self.current
            spans[-1].text = spans[-1].text.rstrip()
            self.paragraphs.append(Paragraph(spans, kind=self.current_kind))
        self.current = []
        self.paragraphs.extend(self.pending)
        self.pending = []

    def add_line(self, spans: list[Span], kind: str, new_paragraph: bool) -> None:
        if new_paragraph or kind != self.current_kind:
            self.close()
            self.current_kind = kind
        if self.current:
            self._join(spans)
        self.current.extend(spans)

    def _join(self, spans: list[Span]) -> None:
        """Join the previous line to this one: a space, or a rejoined split word (D12)."""
        last = next((s for s in reversed(self.current) if s.reason is None), None)
        first = next((s for s in spans if s.reason is None), None)
        if last is None or first is None:
            return
        head_text = last.text.rstrip()
        tail_text = first.text.lstrip()
        if (
            len(head_text) > 1
            and head_text[-1] in _HYPHENS
            and head_text[-2].isalpha()
            and tail_text[:1].islower()
        ):
            heads = _WORD.findall(head_text[:-1])
            tails = _WORD.findall(tail_text)
            if heads and tails and should_rejoin(heads[-1], tails[0], self.counts):
                last.text = head_text[:-1]
                index = self.current.index(last)
                self.current.insert(index + 1, Span(head_text[-1], Reason.HYPHEN, last.location))
            else:
                last.text = head_text
            first.text = tail_text
            return
        last.text = head_text + " "
        first.text = tail_text

    def removal(self, text: str, reason: Reason, location: Location, *, now: bool) -> None:
        paragraph = Paragraph.removed(text, reason, location)
        if now:
            self.close()
            self.paragraphs.append(paragraph)
        else:
            self.pending.append(paragraph)


def build_book(extracted: Extracted, *, fallback_title: str, language: str | None) -> Book:
    language = book_language(extracted.language, language)
    rules = rules_for(language)
    pages = extracted.pages
    layout = analyse(pages, rules)
    body = layout.body_size
    book = Book(
        title=extracted.title or fallback_title,
        author=extracted.author,
        language=language,
        source_format="pdf",
    )
    for page in pages:
        if page.is_scan:
            book.flags.append(PageFlag(page.number, "scanned", SCANNED_PAGE_MESSAGE))
        if page.number in layout.multi_column:
            book.flags.append(PageFlag(page.number, "multi_column", MULTI_COLUMN_MESSAGE))

    counts = word_counts(line.text for page in pages for line in page.lines)
    builder = _Builder(counts)
    note_builder = _Builder(counts)  # footnotes, joined like body text
    prev: Line | None = None
    drop_cap_bottom: float | None = None  # lines beside a drop cap are indented
    drop_cap_page = 0

    for page in pages:
        lines = [ln for ln in page.lines if layout.roles.get(id(ln)) is None]
        left = sorted(ln.x0 for ln in lines)[len(lines) // 10] if lines else 0
        right = sorted(ln.x1 for ln in lines)[(len(lines) * 9) // 10] if lines else page.width
        for line in page.lines:
            role = layout.roles.get(id(line))
            location = Location(page=page.number, top=round(line.top, 1))
            if role and role.reason:
                builder.removal(line.text, role.reason, location, now=False)
                continue
            if page.number in layout.multi_column:  # notes too: never read interleaved
                builder.removal(line.text, Reason.MULTI_COLUMN, location, now=False)
                continue
            if role and role.note:
                spans = _line_spans(line, layout)
                starts = bool(_NOTE_START.match(_text_of(spans).strip() + " "))
                # A note without a marker runs on from the line (or page) before.
                note_builder.add_line(spans, "note", starts or not note_builder.current)
                continue
            kind = "heading" if line.size >= 1.15 * body else "text"
            beside_drop_cap = (
                drop_cap_bottom is not None
                and line.page == drop_cap_page
                and line.top < drop_cap_bottom
            )
            new = _starts_paragraph(line, prev, layout, left, right, beside_drop_cap)
            first = line.words[0]
            if len(first.text) == 1 and first.text.isupper() and first.size >= 1.6 * line.size:
                drop_cap_bottom, drop_cap_page = first.bottom, line.page
            builder.add_line(_line_spans(line, layout), kind, new)
            prev = line
    builder.close()
    note_builder.close()
    notes = note_builder.paragraphs

    paragraphs = builder.paragraphs
    for paragraph in paragraphs:
        if (
            paragraph.kind == "text"
            and rules.is_caption(paragraph.text)
            and len(paragraph.text) < 400
        ):
            for span in paragraph.spans:
                span.reason = span.reason or Reason.CAPTION

    book.chapters = _chapters(paragraphs, notes, extracted, rules, book.title)
    return book


def _starts_paragraph(
    line: Line,
    prev: Line | None,
    layout: Layout,
    left: float,
    right: float,
    beside_drop_cap: bool = False,
) -> bool:
    if prev is None:
        return True
    size = line.size
    if line.page == prev.page and line.top - prev.top > 1.45 * layout.line_gap:
        return True  # a blank line between them
    # Otherwise a paragraph only ends where a sentence ends: indents, short lines and font
    # sizes are too noisy on their own (OCR layers shift words and guess sizes), and a
    # line ending in a hyphen or a comma never ends a paragraph.
    if not _SENTENCE_END.search(prev.text.strip()):
        return False
    prev_short = prev.x1 < right - 3 * size
    indented = line.x0 > left + 0.7 * size and not beside_drop_cap
    resized = abs(size - prev.size) > 0.8
    return bool(prev_short or indented or resized)


def _first_page(paragraph: Paragraph) -> int | None:
    return next((s.location.page for s in paragraph.spans if s.location.page), None)


def _chapters(
    paragraphs: list[Paragraph],
    notes: list[Paragraph],
    extracted: Extracted,
    rules,
    title: str,
) -> list[Chapter]:
    front: list[Paragraph] = []
    chapters: list[Chapter] = []
    bookmarks = sorted(
        ((page, name) for name, page in extracted.bookmarks), key=lambda mark: mark[0]
    )
    use_bookmarks = len(bookmarks) >= 2
    marks = iter(bookmarks)
    next_mark = next(marks, None)
    current: Chapter | None = None

    for paragraph in paragraphs:
        page = _first_page(paragraph)
        heading = paragraph.kind == "heading" and paragraph.text
        if use_bookmarks:
            while next_mark is not None and page is not None and page >= next_mark[0]:
                current = Chapter(title=next_mark[1], start_page=next_mark[0])
                chapters.append(current)
                next_mark = next(marks, None)
        elif heading and rules.is_chapter_heading(paragraph.text):
            only_headings = current is not None and all(
                p.kind == "heading" for p in current.paragraphs
            )
            if only_headings:
                current.title += " " + paragraph.text  # "BOOK II" then "CHAPTER I"
            else:
                current = Chapter(title=paragraph.text, start_page=page)
                chapters.append(current)
        elif (
            heading and current is not None and all(p.kind == "heading" for p in current.paragraphs)
        ):
            current.title += ": " + paragraph.text  # "CHAPTER I" then its title
        (current.paragraphs if current else front).append(paragraph)

    if chapters:
        result = finish_chapters(chapters, front, title, rules)
    else:
        result = [Chapter(title=title, paragraphs=front)]

    # Footnotes go to the end of the chapter their page belongs to (D11).
    for note in notes:
        page = _first_page(note) or 0
        owner = result[0]
        for chapter in result:
            start = chapter.start_page or _first_page_of(chapter)
            if start is not None and start <= page:
                owner = chapter
        owner.notes.append(note)
    return result


def _first_page_of(chapter: Chapter) -> int | None:
    return next((p for p in map(_first_page, chapter.paragraphs) if p is not None), None)
