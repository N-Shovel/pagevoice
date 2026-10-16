"""Text-level fixes shared by all formats: ligatures, soft hyphens, hyphenated line breaks.

These repair extraction artefacts; they don't remove words. A line-break hyphen that is
taken out is still recorded as a HYPHEN span so the review can show it.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

from pagevoice.document import Location, Reason, Span

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Ĳ": "IJ",
    "ĳ": "ij",
}
SOFT_HYPHEN = "­"
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_HYPHENS = "-‐‑"


def fix_characters(text: str) -> str:
    """Spell out ligatures, drop soft hyphens and zero-width characters, tidy spaces."""
    for lig, plain in LIGATURES.items():
        text = text.replace(lig, plain)
    text = text.replace(SOFT_HYPHEN, "").replace("​", "").replace("﻿", "")
    text = text.replace(" ", " ")
    return unicodedata.normalize("NFC", text)


def word_counts(texts: Iterable[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(w.lower() for w in _WORD.findall(text))
    return counts


def should_rejoin(head: str, tail: str, counts: Counter[str]) -> bool:
    """D12: rejoin "well-" + "known" only with evidence.

    Rejoin if the joined form appears elsewhere in the book, or the hyphenated form
    doesn't. Otherwise keep the hyphen ("well-known" stays "well-known").
    """
    joined = (head + tail).lower()
    hyphenated = f"{head}-{tail}".lower()
    if counts[joined]:
        return True
    return not counts[hyphenated]


def join_lines(lines: list[tuple[str, Location]], counts: Counter[str]) -> list[Span]:
    """Join wrapped lines into one paragraph's spans, rejoining split words by D12."""
    spans: list[Span] = []
    for index, (line, location) in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        nxt = lines[index + 1][0].lstrip() if index + 1 < len(lines) else ""
        if (
            nxt
            and len(text) > 1
            and text[-1] in _HYPHENS
            and text[-2].isalpha()
            and nxt[:1].isalpha()
            and nxt[:1].islower()
        ):
            head = _WORD.findall(text[:-1])[-1] if _WORD.findall(text[:-1]) else ""
            tail_match = _WORD.match(nxt)
            tail = tail_match.group(0) if tail_match else ""
            if head and tail and should_rejoin(head, tail.split("-")[0], counts):
                spans.append(Span(text[:-1], location=location))
                spans.append(Span(text[-1], Reason.HYPHEN, location))
                continue
            spans.append(Span(text, location=location))  # real hyphen: no space after
            continue
        spans.append(Span(text + " ", location=location))
    if spans:
        last = spans[-1]
        if last.reason is None:
            last.text = last.text.rstrip()
    return spans


def split_markers(spans: list[Span], pattern: re.Pattern) -> list[Span]:
    """Turn note markers inside kept spans ("[1]") into FOOTNOTE_MARKER removals."""
    out: list[Span] = []
    for span in spans:
        if span.reason is not None or not pattern.search(span.text):
            out.append(span)
            continue
        pos = 0
        for match in pattern.finditer(span.text):
            if match.start() > pos:
                out.append(Span(span.text[pos : match.start()], location=span.location))
            out.append(Span(match.group(0), Reason.FOOTNOTE_MARKER, span.location))
            pos = match.end()
        if pos < len(span.text):
            out.append(Span(span.text[pos:], location=span.location))
    return out
