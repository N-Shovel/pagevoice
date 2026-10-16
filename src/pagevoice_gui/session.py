"""The open book: the cleaned text, its identity, and saving review edits in the background."""

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from pagevoice import project
from pagevoice.document import Book
from pagevoice_gui.tasks import run_task

log = logging.getLogger(__name__)


class Session(QObject):
    """One open book. edited fires after any review edit (the render plan is then stale)."""

    edited = Signal()

    def __init__(self, book: Book, book_id: str, source: Path, *, resumed: bool = False) -> None:
        super().__init__()
        self.book, self.book_id, self.source, self.resumed = book, book_id, source, resumed
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.save_now)
        self._save_lock = threading.Lock()  # one save at a time
        self._made = 0  # snapshots taken
        self._written = 0  # newest snapshot on disk: an older one never overwrites it

    def changed(self) -> None:
        """Call after every edit: saves soon (batched), and tells the render page."""
        self._save_timer.start()
        self.edited.emit()

    def save_now(self) -> None:
        self._save_timer.stop()
        data = project.to_dict(self.book)  # snapshot on the UI thread: edits can't race it
        book_id, source = self.book_id, self.source
        self._made += 1
        number = self._made

        def write(_report):
            book = project.from_dict(data)
            with self._save_lock:
                if number > self._written:
                    project.save(book, book_id, source=source)
                    self._written = number

        run_task(write, on_failed=lambda exc: log.error("Saving the review failed: %s", exc))

    @property
    def pronunciations_path(self) -> Path:
        return project.pronunciations_path(self.book_id)


def open_book(path: Path, report) -> tuple[str, Book, bool]:
    """Worker side of opening a book: hash it, then reuse its saved review or clean it.
    Returns (book_id, book, resumed); the Session itself is made on the UI thread."""
    from pagevoice.ingest import read_book

    report("Reading the book…")
    book_id = project.book_id(path)
    saved = project.load(book_id)
    if saved is not None:
        return book_id, saved, True
    report("Cleaning up the text…")
    return book_id, read_book(path), False
