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
    """One open book. edited fires after any review edit (the render plan is then stale).

    lock guards the book: review edits (tiny) take it on the UI thread, and saves take it on
    a worker while they copy the book. A save copies and writes under the lock, so saves
    land in the order they started and the newest edits are always the ones on disk."""

    edited = Signal()

    def __init__(self, book: Book, book_id: str, source: Path, *, resumed: bool = False) -> None:
        super().__init__()
        self.book, self.book_id, self.source, self.resumed = book, book_id, source, resumed
        self.lock = threading.RLock()
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.save_now)

    def changed(self) -> None:
        """Call after every edit: saves soon (batched), and tells the render page."""
        self._save_timer.start()
        self.edited.emit()

    def save_now(self) -> None:
        self._save_timer.stop()
        book, book_id, source, lock = self.book, self.book_id, self.source, self.lock

        def write(_report):
            with lock:
                project.save(book, book_id, source=source)

        run_task(write, on_failed=lambda exc: log.error("Saving the review failed: %s", exc))

    @property
    def pronunciations_path(self) -> Path:
        return project.pronunciations_path(self.book_id)


class Opened:
    """What opening a book produced, handed from the worker to the UI thread."""

    def __init__(self, book_id: str, book: Book, resumed: bool, notice: str = "") -> None:
        self.book_id, self.book, self.resumed, self.notice = book_id, book, resumed, notice


def open_book(path: Path, report, *, language: str | None = None) -> Opened:
    """Worker side of opening a book: hash it, then reuse its saved review or clean it.

    language overrides the book's own label (e.g. an English book marked as French); the
    GUI passes it only after asking. Otherwise LanguageNotSupported reaches the caller."""
    from pagevoice.ingest import read_book

    report("hashing")
    book_id = project.book_id(path)
    notice = ""
    if language is None:
        try:
            saved = project.load(book_id)
        except project.SavedReviewUnreadable as exc:
            log.warning("%s", exc)
            saved, notice = None, str(exc)
        if saved is not None:
            return Opened(book_id, saved, True)
    report("cleaning")
    return Opened(book_id, read_book(path, language=language), False, notice)
