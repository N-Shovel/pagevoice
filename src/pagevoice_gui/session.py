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

    Review edits happen on the UI thread and never wait for anything. A save copies the
    book on a worker; if an edit lands during the copy (the edit counter moved), it copies
    again. Saves are written one at a time, and an older copy never replaces a newer one."""

    edited = Signal()

    def __init__(self, book: Book, book_id: str, source: Path, *, resumed: bool = False) -> None:
        super().__init__()
        self.book, self.book_id, self.source, self.resumed = book, book_id, source, resumed
        self.edits = 0  # bumped by every edit (UI thread)
        self.saving = threading.Lock()  # one write at a time
        self._written = -1  # the edit count of the copy last written
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.save_now)

    def changed(self) -> None:
        """Call after every edit: saves soon (batched), and tells the render page."""
        self.edits += 1
        self._save_timer.start()
        self.edited.emit()

    def save_now(self) -> None:
        self._save_timer.stop()
        run_task(lambda _report: self.write(),
                 on_failed=lambda exc: log.error("Saving the review failed: %s", exc))  # fmt: skip

    def write(self) -> None:
        """Worker side of a save: a consistent copy without blocking edits, then write."""
        for _attempt in range(10):
            count = self.edits
            try:
                data = project.to_dict(self.book)
            except RuntimeError:  # the book changed shape mid-copy
                continue
            if count == self.edits:
                break
        else:
            log.warning("The book kept changing while saving; saved the latest copy")
        with self.saving:
            if count > self._written:
                project.write(data, self.book_id, source=self.source)
                self._written = count

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
