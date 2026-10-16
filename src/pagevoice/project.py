"""A book's review edits, saved between sessions.

The whole cleaned book (every span, removed or not, with its reason, location and restored
flag, plus chapter edits) is saved as JSON in the per-user data folder, keyed by the source
file's hash. Opening the same file again picks up where the review left off, and because
the text is the same, so do the render cache keys. A different file, even with the same
name, gets a fresh start.
"""

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from platformdirs import user_data_dir

from pagevoice.document import (
    Book,
    Chapter,
    Location,
    MergedTitle,
    PageFlag,
    Paragraph,
    Reason,
    Span,
)

FORMAT = 1


def book_id(path: Path) -> str:
    """The book's identity: a hash of the source file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()[:16]


def projects_dir() -> Path:
    override = os.environ.get("PAGEVOICE_PROJECTS_DIR")
    if override:
        return Path(override)
    return Path(user_data_dir("PageVoice", appauthor=False)) / "books"


def to_dict(book: Book) -> dict:
    data = asdict(book)
    data["cover"] = base64.b64encode(book.cover).decode("ascii") if book.cover else None
    return {"format": FORMAT, "book": data}


def _span(data: dict) -> Span:
    reason = Reason(data["reason"]) if data["reason"] else None
    return Span(data["text"], reason, Location(**data["location"]), data["restored"])


def _paragraph(data: dict) -> Paragraph:
    return Paragraph([_span(s) for s in data["spans"]], data["kind"])


def from_dict(data: dict) -> Book:
    if data.get("format") != FORMAT:
        raise ValueError("Saved review from a different PageVoice version")
    b = data["book"]
    return Book(
        title=b["title"],
        language=b["language"],
        author=b["author"],
        chapters=[
            Chapter(
                c["title"],
                [_paragraph(p) for p in c["paragraphs"]],
                [_paragraph(p) for p in c["notes"]],
                c["start_page"],
                [MergedTitle(**m) for m in c.get("merged", [])],
            )
            for c in b["chapters"]
        ],
        flags=[PageFlag(**f) for f in b["flags"]],
        cover=base64.b64decode(b["cover"]) if b["cover"] else None,
        cover_type=b["cover_type"],
        source_format=b["source_format"],
    )


def save(book: Book, book_id: str, *, source: Path | None = None) -> Path:
    """Save the book's review state (atomically)."""
    folder = projects_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{book_id}.json"
    data = to_dict(book)
    data["source"] = str(source) if source else None
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _replace(tmp, path)
    return path


def _replace(tmp: Path, path: Path, attempts: int = 20) -> None:
    """os.replace, retried: on Windows it fails while anything (a reader, an antivirus
    scan) has the target open, and that clears within moments."""
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


class SavedReviewUnreadable(RuntimeError):
    """The saved review exists but can't be read (damaged, or from another version). It was
    kept as a .bak file, so the user's edits aren't silently lost."""

    def __init__(self, backup: Path) -> None:
        super().__init__(
            "Your saved review of this book couldn't be read, so the book was cleaned again "
            f"from the original. The old review was kept as {backup}."
        )
        self.backup = backup


def load(book_id: str) -> Book | None:
    """The saved review for this book, or None if there is none.

    Raises SavedReviewUnreadable if there is one that can't be read. It's moved aside
    first, so the next load starts fresh."""
    path = projects_dir() / f"{book_id}.json"
    for attempt in range(20):
        try:
            text = path.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return None
        except PermissionError:  # Windows, while a save is replacing the file
            if attempt == 19:
                raise
            time.sleep(0.05)
    try:
        return from_dict(json.loads(text))
    except (ValueError, KeyError, TypeError) as exc:
        backup = path.with_suffix(".json.bak")
        _replace(path, backup)
        raise SavedReviewUnreadable(backup) from exc


def pronunciations_path(book_id: str) -> Path:
    """The book's own pronunciation list (TSV), next to its saved review (SPEC §5)."""
    return projects_dir() / f"{book_id}.pronunciations.tsv"


def forget(book_id: str) -> None:
    """Drop the saved review, e.g. to clean the book again from scratch."""
    (projects_dir() / f"{book_id}.json").unlink(missing_ok=True)
