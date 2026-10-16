"""The main window: open a book → review → voice and export (SPEC §12, M4)."""

import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
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
from pagevoice.document import IngestError
from pagevoice.pronounce.store import global_path
from pagevoice.render.cache import RenderCache
from pagevoice.render.renderer import speak
from pagevoice.voice.kokoro import SAMPLE_RATE
from pagevoice_gui import playback, tasks
from pagevoice_gui.produce import ProducePage, VoiceFactory
from pagevoice_gui.pronunciations import PronunciationDialog
from pagevoice_gui.review import ReviewPage
from pagevoice_gui.session import Session, open_book

log = logging.getLogger(__name__)
OPEN, REVIEW, PRODUCE = range(3)
BOOK_FILTER = "Books (*.epub *.pdf *.txt);;All files (*)"


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
        self.button = QPushButton(self.tr("Open a book…"), clicked=open_clicked)
        self.button.setMinimumHeight(40)
        layout = QVBoxLayout(self)
        layout.addStretch()
        for widget in (title, self.status, self.button):
            layout.addWidget(widget, alignment=Qt.AlignHCenter)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(
        self,
        voice_factory: VoiceFactory,
        voices: list[str],
        cache: RenderCache | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("PageVoice")
        self.resize(1100, 760)
        self.setAcceptDrops(True)
        self.voice_factory = voice_factory
        self.session: Session | None = None
        self._busy = False

        self.open_page = OpenPage(self.choose_book)
        self.review_page = ReviewPage()
        self.produce_page = ProducePage(voice_factory, voices, cache or RenderCache())
        self.review_page.continue_clicked.connect(lambda: self.show_step(PRODUCE))
        self.review_page.clean_again_clicked.connect(self.clean_again)
        self.produce_page.review_clicked.connect(lambda: self.show_step(REVIEW))
        self.produce_page.pronunciations_clicked.connect(self.edit_pronunciations)
        self.produce_page.busy_changed.connect(self._set_busy)

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
        quit_action = QAction(self.tr("&Quit"), self, shortcut=QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        for action in (self.open_action, pronunciations, quit_action):
            file_menu.addAction(action)
        self.show_step(OPEN)

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
        has_book = self.session is not None
        self.steps.button(OPEN).setEnabled(not self._busy)
        self.steps.button(REVIEW).setEnabled(has_book and not self._busy)
        self.steps.button(PRODUCE).setEnabled(has_book)
        self.open_action.setEnabled(not self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_steps()

    # --- opening ---

    def choose_book(self) -> None:
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Open a book"), "", self.tr(BOOK_FILTER)
        )
        if path:
            self.load_book(Path(path))

    def load_book(self, path: Path) -> None:
        path = Path(path).resolve()
        if self.session is not None:
            self.session.save_now()
        self.show_step(OPEN)
        self.open_page.button.setEnabled(False)
        self.open_page.status.setText(self.tr("Opening %1…").replace("%1", path.name))

        def done(result) -> None:
            book_id, book, resumed = result
            self.open_page.button.setEnabled(True)
            self.set_session(Session(book, book_id, path, resumed=resumed))

        def failed(exc) -> None:
            self.open_page.button.setEnabled(True)
            if isinstance(exc, IngestError):
                message = str(exc)  # already plain language
            else:
                log.error("Opening %s failed", path, exc_info=exc)
                message = self.tr("PageVoice couldn't open this file. Details are in the log.")
            self.open_page.status.setText(message)
            QMessageBox.warning(self, self.tr("Open a book"), message)

        tasks.run_task(lambda report: open_book(path, report), on_done=done, on_failed=failed,
                       on_progress=self.open_page.status.setText)  # fmt: skip

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
        if self.session is None:
            return
        project.forget(self.session.book_id)
        source, self.session = self.session.source, None
        self.load_book(source)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and not self._busy:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.load_book(Path(urls[0].toLocalFile()))

    # --- pronunciations ---

    def edit_pronunciations(self) -> None:
        book_path = self.session.pronunciations_path if self.session else None
        dialog = PronunciationDialog(book_path, global_path(), self.preview, self)
        if dialog.exec():
            self.produce_page.plan_changed()

    def preview(self, text: str, entries) -> None:
        voice_name = self.produce_page.voice.currentData()
        speed = self.produce_page.speed.value()
        language = self.session.book.language if self.session else "en"

        def work(_report) -> Path:
            voice = self.voice_factory(voice_name, "cpu")
            if not voice.ready():
                raise RuntimeError("voice not downloaded")
            audio = speak(text, voice, language=language, pronunciations=entries, speed=speed)
            path = Path(tempfile.gettempdir()) / "pagevoice-preview.wav"
            write_wav(path, audio, SAMPLE_RATE)
            return path

        def failed(exc) -> None:
            log.error("Preview failed", exc_info=exc)
            QMessageBox.information(
                self,
                self.tr("Preview"),
                self.tr(
                    "The preview needs the voice. Press Render once to download it, then try again."
                )
                if "not downloaded" in str(exc)
                else str(exc),
            )

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
                self.tr(
                    "PageVoice is still working. Stop and quit? Rendering carries on from here "
                    "next time."
                ),
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.produce_page.stop_work()
        if self.session is not None:
            project.save(self.session.book, self.session.book_id, source=self.session.source)
        tasks.wait_for_all(15000)
        event.accept()
