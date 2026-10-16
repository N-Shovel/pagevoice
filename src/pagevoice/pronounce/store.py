"""Where pronunciation lists live: one global list per user; per-book lists sit with the
book's project (M4)."""

import os
from pathlib import Path

from platformdirs import user_data_dir

from pagevoice.pronounce.lexicon import Entry, load, merge


def global_path() -> Path:
    override = os.environ.get("PAGEVOICE_DATA_DIR")
    base = Path(override) if override else Path(user_data_dir("PageVoice", appauthor=False))
    return base / "pronunciations.tsv"


def entries_for(book_list: Path | None = None) -> list[Entry]:
    """The global list with a book's list on top (D15)."""
    global_file = global_path()
    global_entries = load(global_file) if global_file.exists() else []
    book_entries = load(book_list) if book_list and book_list.exists() else []
    return merge(global_entries, book_entries)
