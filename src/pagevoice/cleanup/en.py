"""English text patterns for cleanup. Language module: keyed by the book's language."""

import re

# "Chapter 12", "CHAPTER XII", "Chapter the First", "BOOK II. CHAPTER I.", "Part One"
_NUMBER = (
    r"(?:\d+|[IVXLCDM]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|the\s+\w+)"
)
CHAPTER = re.compile(
    rf"^\s*(?:(?:book|part|volume)\s+{_NUMBER}\.?\s*)?(?:chapter|letter|stave)\s+{_NUMBER}\b.*$|"
    rf"^\s*(?:book|part|volume)\s+{_NUMBER}\b\.?\s*$|"
    r"^\s*(?:prologue|epilogue|preface|introduction|foreword|afterword)\s*\.?\s*$",
    re.IGNORECASE,
)
# "Figure 1. The lantern room", "Table 2: Harvests", "Plate IV", "Fig. 3 The coast". Not
# "Table 2 shows that…": after the number comes punctuation, a capital or the end.
_CAPTION_START = r"^\s*(?i:fig(?:ure)?\.?|table|plate|illustration)\s+[\dIVXLC]+[a-z]?"
CAPTION = re.compile(_CAPTION_START + r"(?:\s*[.:–—-]|\s+[^\sa-z]|\s*$)")
_CAPTION_WORD = re.compile(_CAPTION_START + r"\s+[a-z]")
# One-letter words: a drop cap that is one ("I was born", "A long time") keeps its space.
ONE_LETTER_WORDS = frozenset({"A", "I"})

# Project Gutenberg plain text marks pictures as "[Illustration: caption]", sometimes
# over several blank-line-separated blocks.
ILLUSTRATION_START = re.compile(r"^\s*\[Illustrations?\b", re.I)
# Splits a marker block into its opening, the text inside, and the closing bracket.
ILLUSTRATION_PARTS = re.compile(r"^(\[Illustrations?:?\s*|)(.*?)(\]?)$", re.S | re.I)

# Project Gutenberg plain-text notes: "[Footnote 1: text]" blocks, "[1]" markers in text.
FOOTNOTE_BLOCK = re.compile(r"^\s*\[(?:Footnote|Note)\s*[\w*†‡]{0,4}\s*:\s*", re.I)
FOOTNOTE_REF = re.compile(r"\[(?:\d{1,3}|[A-Z]|[*†‡])\]")

CONTENTS = re.compile(r"^\s*(?:table of )?contents\.?\s*$", re.I)

GUTENBERG_START = re.compile(r"^\s*\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
GUTENBERG_END = re.compile(r"^\s*\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
GUTENBERG_FIELD = re.compile(r"^(Title|Author|Language):\s*(.+)$", re.M)


def is_chapter_heading(text: str) -> bool:
    return len(text) <= 80 and bool(CHAPTER.match(text))


def is_caption(text: str) -> bool:
    """A caption's opening. "Table 2 shows that…" is a sentence about a table, not one."""
    return bool(CAPTION.match(text)) and not _CAPTION_WORD.match(text)


FRONT_MATTER_TITLE = "Front matter"
SECTION_TITLE = "Section {n}"
