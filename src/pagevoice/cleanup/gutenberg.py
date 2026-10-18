"""Project Gutenberg's own plain-text markers.

These are PG's file format, the same in every PG book whatever its language (the licence
header is always English), and they're read before the book's language is known. So they
live here, not in a language module (rule 7)."""

import re

START = re.compile(r"^\s*\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
END = re.compile(r"^\s*\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG", re.I)
FIELD = re.compile(r"^(Title|Author|Language):\s*(.+)$", re.M)
