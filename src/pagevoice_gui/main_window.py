"""The main window: open a book → review → voice and export (SPEC §12, M4)."""

import logging
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pagevoice import project
from pagevoice.audio import write_wav
from pagevoice.cleanup.language import LanguageNotSupported
from pagevoice.document import IngestError
from pagevoice.pronounce.store import global_path
from pagevoice.render.cache import RenderCache
from pagevoice.render.renderer import speak
from pagevoice.voice.engine import VoiceSetup
from pagevoice.voice.kokoro import SAMPLE_RATE
from pagevoice_gui import playback, tasks
from pagevoice_gui.produce import ProducePage, VoiceFactory, VoiceUnavailable
from pagevoice_gui.pronunciations import PronunciationDialog
from pagevoice_gui.review import ReviewPage
from pagevoice_gui.session import Opened, Session, open_book
from pagevoice_gui.settings_dialog import SettingsDialog, cache_cap_bytes

log = logging.getLogger(__name__)
OPEN, REVIEW, PRODUCE = range(3)


class VoiceNotDownloaded(RuntimeError):
    """A preview was asked for before the first-run download."""


class OpenPage(QWidget):
    def __init__(self, open_clicked, parent=None) -> None:
        super().__init__(parent)
        title = QLabel(self.tr("Turn a book into an audiobook"))
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.status = QLabel(
            self.tr(
                "Open an EPUB, a PDF with real text, or a TXT file, or drop it on this window. "
                "Everything happens on this computer."
            ),
            wordWrap=True,
        )
        self.button = QPushButton(self.tr("Open a book…"), clicked=lambda: open_clicked())
        self.button.setMinimumHeight(40)
        title.setAlignment(Qt.AlignHCenter)
        self.status.setAlignment(Qt.AlignHCenter)
        # A centred column of fixed width: a word-wrapped label needs a width to wrap to,
        # or Qt squeezes it and the lines overlap.
        column = QWidget()
        column.setFixedWidth(520)
        inner = QVBoxLayout(column)
        inner.addWidget(title)
        inner.addWidget(self.status)
        inner.addWidget(self.button, alignment=Qt.AlignHCenter)
        # Centred with stretches, not alignment flags: an aligned item loses Qt's
        # height-for-width, and the wrapped text gets squeezed again.
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(column)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addLayout(row)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(
        self,
        voice_factory: VoiceFactory,
        voices: list[str],
        cache: RenderCache | None = None,
        *,
        dml: bool = False,
        allow_upstream_download: bool = False,
    ) -> None:
        super().__init__()
        self.setWindowTitle("PageVoice")
        self.resize(1100, 760)
        self.setAcceptDrops(True)
        self._voices: dict[tuple[str, str], VoiceSetup] = {}
        self._voices_lock = threading.Lock()
        self._raw_factory = voice_factory
        self.session: Session | None = None
        self._busy = self._opening = False
        self.cache = cache or RenderCache(cap_bytes=cache_cap_bytes())

        self.open_page = OpenPage(self.choose_book)
        self.review_page = ReviewPage()
        self.produce_page = ProducePage(
            self.voice_factory, voices, self.cache,
            dml=dml, allow_upstream_download=allow_upstream_download,
        )  # fmt: skip
        self.review_page.continue_clicked.connect(lambda: self.show_step(PRODUCE))
        self.review_page.clean_again_clicked.connect(self.clean_again)
        self.produce_page.review_clicked.connect(lambda: self.show_step(REVIEW))
        self.produce_page.pronunciations_clicked.connect(self.edit_pronunciations)
        self.produce_page.busy_changed.connect(self._set_busy)
        self.produce_page.notes_setting_changed.connect(self.review_page.refresh)

        self.stack = QStackedWidget()
        for page in (self.open_page, self.review_page, self.produce_page):
            self.stack.addWidget(page)

        self.steps = QButtonGroup(self)
        step_bar = QHBoxLayout()
        labels = (self.tr("1. Open"), self.tr("2. Review"), self.tr("3. Voice and export"))
        for index, label in enumerate(labels):
            button = QPushButton(label, checkable=True)
            self.steps.addButton(button, index)
            step_bar.addWidget(button)
        step_bar.addStretch()
        self.steps.idClicked.connect(self.show_step)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(step_bar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        file_menu = self.menuBar().addMenu(self.tr("&File"))
        self.open_action = QAction(self.tr("&Open a book…"), self, shortcut=QKeySequence.Open)
        self.open_action.triggered.connect(self.choose_book)
        pronunciations = QAction(self.tr("&Pronunciations…"), self)
        pronunciations.triggered.connect(self.edit_pronunciations)
        settings = QAction(self.tr("&Settings…"), self)
        settings.triggered.connect(self.edit_settings)
        quit_action = QAction(self.tr("&Quit"), self, shortcut=QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        for action in (self.open_action, pronunciations, settings, quit_action):
            file_menu.addAction(action)
        self.show_step(OPEN)

    def voice_factory(self, name: str, provider: str) -> VoiceSetup:
        """One voice per (name, provider), shared by rendering and previews: its checksum
        is checked once, and the model is loaded once (VoiceSetup is thread-safe)."""
        with self._voices_lock:
            key = (name, provider)
            if key not in self._voices:
                self._voices[key] = self._raw_factory(name, provider)
            return self._voices[key]

    # --- steps ---

    def show_step(self, step: int) -> None:
        if step != OPEN and self.session is None:
            step = OPEN
        if step == REVIEW and self._busy:
            step = PRODUCE  # no review edits while rendering or exporting
        self.stack.setCurrentIndex(step)
        self.steps.button(step).setChecked(True)
        self._update_steps()

    def _update_steps(self) -> None:
        has_book, free = self.session is not None, not (self._busy or self._opening)
        self.steps.button(OPEN).setEnabled(free)
        self.steps.button(REVIEW).setEnabled(has_book and free)
        self.steps.button(PRODUCE).setEnabled(has_book and not self._opening)
        self.open_action.setEnabled(free)
        self.open_page.button.setEnabled(free)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_steps()

    # --- opening ---

    def choose_book(self) -> None:
        if self._busy or self._opening:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Open a book"), "", self.tr("Books (*.epub *.pdf *.txt);;All files (*)")
        )
        if path:
            self.load_book(Path(path))

    def load_book(self, path: Path, language: str | None = None) -> None:
        if self._busy or self._opening:
            return
        path = Path(path).resolve()
        if self.session is not None:
            self.session.save_now()
        self._opening = True
        self.show_step(OPEN)
        steps = {"hashing": self.tr("Opening %1…").replace("%1", path.name),
                 "cleaning": self.tr("Cleaning up %1…").replace("%1", path.name)}  # fmt: skip
        self.open_page.status.setText(steps["hashing"])

        def done(opened: Opened) -> None:
            self._opening = False
            self.set_session(Session(opened.book, opened.book_id, path, resumed=opened.resumed))
            if opened.notice:
                QMessageBox.information(self, self.tr("Open a book"), opened.notice)

        def failed(exc) -> None:
            self._opening = False
            self._update_steps()
            if isinstance(exc, LanguageNotSupported) and language is None:
                answer = QMessageBox.question(
                    self,
                    self.tr("Open a book"),
                    self.tr("This book is marked as %1. PageVoice reads English only for now. "
                            "If the book really is in English, read it as English anyway?")
                    .replace("%1", exc.name),
                )  # fmt: skip
                if answer == QMessageBox.Yes:
                    self.load_book(path, language="en")
                    return
                message = str(exc)
            elif isinstance(exc, IngestError):
                message = str(exc)  # already plain language
            else:
                log.error("Opening %s failed", path, exc_info=exc)
                message = self.tr("PageVoice couldn't open this file. Details are in the log.")
            self.open_page.status.setText(message)
            QMessageBox.warning(self, self.tr("Open a book"), message)

        tasks.run_task(
            lambda report: open_book(path, report, language=language),
            on_done=done,
            on_failed=failed,
            on_progress=lambda step: self.open_page.status.setText(steps.get(step, step)),
        )
        self._update_steps()

    def set_session(self, session: Session) -> None:
        self.session = session
        self.setWindowTitle(f"{session.book.title} – PageVoice")
        self.review_page.set_session(session)
        self.produce_page.set_session(session)
        if not session.resumed:
            session.save_now()
        # Review is on by default for PDFs, optional for EPUB and TXT (SPEC §4).
        self.show_step(REVIEW if session.book.source_format == "pdf" else PRODUCE)
        self.open_page.status.setText(
            self.tr("Opened %1. Open another book any time.").replace("%1", session.source.name)
        )

    def clean_again(self) -> None:
        if self.session is None or self._busy:
            return
        session, self.session = self.session, None
        book_id, source = session.book_id, session.source

        def forget(_report) -> None:
            with session.lock:  # after any save still in flight
                project.forget(book_id)

        tasks.run_task(forget, on_done=lambda _r: self.load_book(source))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and not (self._busy or self._opening):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.load_book(Path(urls[0].toLocalFile()))

    # --- pronunciations and settings ---

    def edit_pronunciations(self) -> None:
        book_path = self.session.pronunciations_path if self.session else None
        dialog = PronunciationDialog(book_path, global_path(), self.preview, self)
        if dialog.exec():
            self.produce_page.plan_changed()

    def edit_settings(self) -> None:
        SettingsDialog(self.cache, self._busy, self).exec()

    def preview(self, text: str, entries) -> None:
        page = self.produce_page
        voice_name, speed = page.voice.currentData(), page.speed.value()
        provider = "dml" if page.use_gpu.isChecked() else "cpu"
        language = self.session.book.language if self.session else "en"
        factory = self.voice_factory

        def work(_report) -> Path:
            voice = factory(voice_name, provider)
            if not voice.ready():
                raise VoiceNotDownloaded
            audio = speak(text, voice, language=language, pronunciations=entries, speed=speed)
            path = Path(tempfile.gettempdir()) / "pagevoice-preview.wav"
            write_wav(path, audio, SAMPLE_RATE)
            return path

        def failed(exc) -> None:
            if isinstance(exc, VoiceNotDownloaded):
                message = self.tr("The preview needs the voice. Press Render once to download "
                                  "it, then try again.")  # fmt: skip
            elif isinstance(exc, VoiceUnavailable):
                message = str(exc)
            else:
                log.error("Preview failed", exc_info=exc)
                message = self.tr("The preview couldn't be made. Details are in the log.")
            QMessageBox.information(self, self.tr("Preview"), message)

        def done(path: Path) -> None:
            try:
                playback.play(path)
            except playback.PlaybackError as exc:
                QMessageBox.information(self, self.tr("Preview"), str(exc))

        tasks.run_task(work, on_done=done, on_failed=failed)

    # --- quitting ---

    def closeEvent(self, event) -> None:
        if self._busy:
            answer = QMessageBox.question(
                self,
                self.tr("Quit PageVoice"),
                self.tr("PageVoice is still working. Stop and quit? Rendering carries on from "
                        "here next time."),
            )  # fmt: skip
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.produce_page.stop_work()
        if self.session is not None:
            self.session.save_now()  # through the ordered worker save
        # The window goes away at once; workers get a moment to stop and finish saving.
        self.hide()
        QApplication.processEvents()
        if not tasks.wait_for_all(15000):
            log.warning(QCoreApplication.translate("MainWindow", "Some work didn't stop in time"))
        event.accept()
