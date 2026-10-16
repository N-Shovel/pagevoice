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
CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?|table|plate|illustration)\s+[\dIVXLC]+[.:\s]", re.I)

# Project Gutenberg plain text marks pictures as "[Illustration: caption]", sometimes
# over several blank-line-separated blocks.
ILLUSTRATION_START = re.compile(r"^\s*\[Illustrations?\b", re.I)

GUTENBERG_START = re.compile(r"^\s*\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
GUTENBERG_END = re.compile(r"^\s*\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
GUTENBERG_FIELD = re.compile(r"^(Title|Author|Language):\s*(.+)$", re.M)


def is_chapter_heading(text: str) -> bool:
    return len(text) <= 80 and bool(CHAPTER.match(text))


def is_caption(text: str) -> bool:
    return bool(CAPTION.match(text))


FRONT_MATTER_TITLE = "Front matter"
SECTION_TITLE = "Section {n}"
