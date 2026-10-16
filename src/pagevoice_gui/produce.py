"""Voice, render and export (SPEC §6, §8): pick the voice, render with progress, pause and
resume (also after a restart, through the render cache), then write the M4B or MP3s."""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pagevoice.export.audiobook import Metadata, export_m4b, export_mp3
from pagevoice.export.ffmpeg import Cancelled, FfmpegError
from pagevoice.pronounce.store import entries_for
from pagevoice.render.cache import RenderCache
from pagevoice.render.renderer import Progress, Renderer, RenderSettings
from pagevoice.voice.engine import DEFAULT_VOICE, VoiceSetup
from pagevoice_gui.session import Session
from pagevoice_gui.tasks import run_task

log = logging.getLogger(__name__)

VoiceFactory = Callable[[str, str], VoiceSetup]  # (voice name, provider) -> voice
ACCENTS = {"a": "American", "b": "British"}
GENDERS = {"f": "female", "m": "male"}


def voice_label(name: str) -> str:
    """'af_heart' -> 'Heart (American, female)'."""
    prefix, _, rest = name.partition("_")
    if len(prefix) == 2 and prefix[0] in ACCENTS and prefix[1] in GENDERS:
        return f"{rest.title()} ({ACCENTS[prefix[0]]}, {GENDERS[prefix[1]]})"
    return name


def duration_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


class _Stopped(Exception):
    """The user cancelled the download."""


class ProducePage(QWidget):
    review_clicked = Signal()
    pronunciations_clicked = Signal()
    busy_changed = Signal(bool)  # the main window locks review edits while work runs

    def __init__(
        self, voice_factory: VoiceFactory, voices: list[str], cache: RenderCache, parent=None
    ) -> None:
        super().__init__(parent)
        self.voice_factory, self.cache = voice_factory, cache
        self.session: Session | None = None
        self.renderer: Renderer | None = None
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.settings = QSettings()
        self._busy = False

        # Voice
        self.voice = QComboBox()
        for name in voices:
            self.voice.addItem(voice_label(name), name)
        self.voice.setCurrentIndex(
            max(0, self.voice.findData(self.settings.value("voice", DEFAULT_VOICE)))
        )
        self.speed = QDoubleSpinBox(minimum=0.5, maximum=2.0, singleStep=0.05, decimals=2)
        self.speed.setValue(float(self.settings.value("speed", 1.0)))
        self.speed.setSuffix(" ×")
        self.read_notes = QCheckBox(self.tr("Read footnotes at the end of each chapter"))
        self.read_notes.setChecked(self.settings.value("read_notes", True, type=bool))
        self.voice.currentIndexChanged.connect(self._settings_changed)
        self.speed.valueChanged.connect(self._settings_changed)
        self.read_notes.toggled.connect(self._settings_changed)
        voice_box = QGroupBox(self.tr("Voice"))
        form = QFormLayout(voice_box)
        form.addRow(self.tr("Voice:"), self.voice)
        form.addRow(self.tr("Speed:"), self.speed)
        form.addRow(self.read_notes)
        links = QHBoxLayout()
        links.addWidget(
            QPushButton(self.tr("Pronunciations…"), clicked=self.pronunciations_clicked)
        )
        links.addWidget(QPushButton(self.tr("Back to review"), clicked=self.review_clicked))
        links.addStretch()
        form.addRow(links)

        # Render
        self.render_button = QPushButton(self.tr("Render"), clicked=self.start_render)
        self.pause_button = QPushButton(self.tr("Pause"), clicked=self.toggle_pause, enabled=False)
        self.stop_button = QPushButton(self.tr("Stop"), clicked=self.stop_work, enabled=False)
        self.progress = QProgressBar()
        self.status = QLabel(wordWrap=True)
        self.current = QLabel(wordWrap=True)
        self.current.setStyleSheet("color:#777;")
        self.problems = QListWidget()
        self.problems.hide()
        render_box = QGroupBox(self.tr("Render"))
        render_layout = QVBoxLayout(render_box)
        row = QHBoxLayout()
        for button in (self.render_button, self.pause_button, self.stop_button):
            row.addWidget(button)
        row.addStretch()
        render_layout.addLayout(row)
        render_layout.addWidget(self.progress)
        render_layout.addWidget(self.status)
        render_layout.addWidget(self.current)
        render_layout.addWidget(self.problems)

        # Export
        self.m4b = QRadioButton(self.tr("One M4B audiobook with chapters"))
        self.mp3 = QRadioButton(self.tr("One MP3 per chapter"))
        (self.mp3 if self.settings.value("format") == "mp3" else self.m4b).setChecked(True)
        self.m4b.toggled.connect(self._format_changed)
        self.target = QLineEdit()
        browse = QPushButton(self.tr("Choose…"), clicked=self.choose_target)
        self.free_cache = QCheckBox(
            self.tr("Afterwards, free the rendered audio (keep it if you'll still edit this book)")
        )
        self.free_cache.setChecked(True)
        self.export_button = QPushButton(self.tr("Export"), clicked=self.start_export)
        self.export_progress = QProgressBar()
        self.export_status = QLabel(wordWrap=True)
        export_box = QGroupBox(self.tr("Export"))
        export_layout = QVBoxLayout(export_box)
        export_layout.addWidget(self.m4b)
        export_layout.addWidget(self.mp3)
        target_row = QHBoxLayout()
        target_row.addWidget(self.target, 1)
        target_row.addWidget(browse)
        export_layout.addLayout(target_row)
        export_layout.addWidget(self.free_cache)
        export_layout.addWidget(self.export_button)
        export_layout.addWidget(self.export_progress)
        export_layout.addWidget(self.export_status)

        layout = QVBoxLayout(self)
        layout.addWidget(voice_box)
        layout.addWidget(render_box)
        layout.addWidget(export_box)
        layout.addStretch()

    # --- book and settings ---

    def set_session(self, session: Session) -> None:
        self.session = session
        session.edited.connect(self.plan_changed)
        self.renderer = None
        self._default_target()
        self.status.setText(
            self.tr("Ready. Rendering resumes where it stopped, even after a restart.")
        )
        self.current.clear()
        self.problems.clear()
        self.problems.hide()
        self.progress.setValue(0)
        self.export_progress.setValue(0)
        self.export_status.clear()
        self._update_buttons()

    def plan_changed(self) -> None:
        """Review, pronunciation or voice settings changed: the next render or export
        works out again which paragraphs need audio (changed ones only)."""
        self.renderer = None

    def _settings_changed(self, *_args) -> None:
        self.settings.setValue("voice", self.voice.currentData())
        self.settings.setValue("speed", self.speed.value())
        self.settings.setValue("read_notes", self.read_notes.isChecked())
        self.plan_changed()

    def _format_changed(self) -> None:
        self.settings.setValue("format", "m4b" if self.m4b.isChecked() else "mp3")
        self._default_target()

    def _default_target(self) -> None:
        if not self.session:
            return
        folder = Path(self.settings.value("export_folder", str(self.session.source.parent)))
        name = self.session.source.stem
        self.target.setText(str(folder / (f"{name}.m4b" if self.m4b.isChecked() else name)))

    def choose_target(self) -> None:
        if self.m4b.isChecked():
            path, _ = QFileDialog.getSaveFileName(
                self, self.tr("Save audiobook"), self.target.text(), self.tr("Audiobook (*.m4b)")
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, self.tr("Folder for the MP3 files"), self.target.text()
            )
        if path:
            self.target.setText(path)
            parent = Path(path).parent if self.m4b.isChecked() else Path(path)
            self.settings.setValue("export_folder", str(parent))

    def _update_buttons(self) -> None:
        idle = not self._busy and self.session is not None
        for widget in (self.render_button, self.export_button, self.voice, self.speed):
            widget.setEnabled(idle)
        self.read_notes.setEnabled(idle)
        self.pause_button.setEnabled(self._busy and self._rendering)
        self.stop_button.setEnabled(self._busy)

    _rendering = False

    # --- work ---

    def _planner(self) -> Callable[[Callable], Renderer]:
        """Read the settings here, on the UI thread; the returned function runs on a
        worker: it checks the voice files (hashing ~300 MB) and plans the render."""
        existing = self.renderer
        voice_name, speed = self.voice.currentData(), self.speed.value()
        drop_notes = not self.read_notes.isChecked()
        session, checking, preparing = (
            self.session,
            self.tr("Checking the voice files…"),
            self.tr("Preparing the text…"),
        )

        def plan(report) -> Renderer:
            if existing is not None:
                return existing
            report(checking)
            voice = self.voice_factory(voice_name, "cpu")
            if not voice.ready():
                raise _NeedsDownload(voice)
            report(preparing)
            return Renderer(
                session.book,
                voice,
                self.cache,
                book_id=session.book_id,
                settings=RenderSettings(speed=speed, drop_notes=drop_notes),
                pronunciations=entries_for(session.pronunciations_path),
            )

        return plan

    def _begin(self, rendering: bool) -> None:
        self._busy, self._rendering = True, rendering
        self.busy_changed.emit(True)
        self.stop.clear()
        self.pause.clear()
        self.pause_button.setText(self.tr("Pause"))
        self._update_buttons()

    def _end(self) -> None:
        self._busy = self._rendering = False
        self.busy_changed.emit(False)
        self._update_buttons()

    def start_render(self) -> None:
        plan = self._planner()
        self._begin(rendering=True)
        self.problems.clear()
        self.problems.hide()

        def work(report):
            renderer = plan(report)
            report(renderer)
            return renderer.run(report, stop=self.stop, pause=self.pause)

        run_task(work, on_progress=self._render_progress, on_done=self._render_done,
                 on_failed=self._failed)  # fmt: skip

    def _render_progress(self, value) -> None:
        if isinstance(value, str):
            self.status.setText(value)
        elif isinstance(value, Renderer):
            self.renderer = value
            total = len(value.items)
            done = total - len(value.pending())
            self.progress.setMaximum(max(1, total))
            self.progress.setValue(done)
            message = self.tr("%1 of %2 paragraphs already rendered. Rendering the rest…")
            self.status.setText(message.replace("%1", f"{done:,}").replace("%2", f"{total:,}"))
        elif isinstance(value, Progress):
            self.progress.setMaximum(max(1, value.total))
            self.progress.setValue(value.done)
            parts = [self.tr("%1 of %2 paragraphs").replace("%1", f"{value.done:,}")
                     .replace("%2", f"{value.total:,}")]  # fmt: skip
            if value.eta_seconds is not None:
                parts.append(
                    self.tr("about %1 left").replace("%1", duration_text(value.eta_seconds))
                )
            if value.elapsed > 0:
                parts.append(f"{value.audio_seconds / value.elapsed:.1f}× " + self.tr("real time"))
            if self.pause.is_set():
                parts.append(self.tr("paused"))
            self.status.setText(" · ".join(parts))
            if value.current:
                self.current.setText(value.current.source[:300])

    def _render_done(self, result) -> None:
        self._end()
        self.current.clear()
        for item, warning in result.warnings:
            self.problems.addItem(
                self.tr("Chapter %1: %2 “%3”").replace("%1", str(item.chapter + 1))
                .replace("%2", warning).replace("%3", item.source[:80])
            )  # fmt: skip
        for item, error in result.failed:
            log.error("Paragraph failed: %s", error)
            self.problems.addItem(
                self.tr("Chapter %1: a paragraph couldn't be rendered and will be retried: “%2”")
                .replace("%1", str(item.chapter + 1)).replace("%2", item.source[:80])
            )  # fmt: skip
        self.problems.setVisible(self.problems.count() > 0)
        if result.cancelled:
            self.status.setText(self.tr("Stopped. Press Render to carry on where it stopped."))
        elif result.failed:
            self.status.setText(
                self.tr("%n paragraph(s) failed. Press Render to try them again.", "",
                        len(result.failed))
            )  # fmt: skip
        else:
            self.status.setText(self.tr("Everything is rendered. You can export now."))

    def toggle_pause(self) -> None:
        if self.pause.is_set():
            self.pause.clear()
            self.pause_button.setText(self.tr("Pause"))
        else:
            self.pause.set()
            self.pause_button.setText(self.tr("Resume"))
            self.status.setText(self.status.text() + " · " + self.tr("paused"))

    def stop_work(self) -> None:
        self.stop.set()
        self.pause.clear()

    def start_export(self) -> None:
        target = Path(self.target.text().strip()) if self.target.text().strip() else None
        if target is None:
            self.choose_target()
            return
        plan = self._planner()
        self._begin(rendering=False)
        as_mp3, clear = self.mp3.isChecked(), self.free_cache.isChecked()
        self.export_status.setText(self.tr("Checking that everything is rendered…"))

        def work(report):
            renderer = plan(lambda _msg: None)
            report(renderer)
            pending = len(renderer.pending())
            if pending:
                return pending
            options = dict(
                meta=Metadata.from_book(renderer.book),
                progress=lambda step, fraction: report((step, fraction)),
                stop=self.stop,
                clear_cache=clear,
            )
            if as_mp3:
                return export_mp3(renderer, target, **options)
            return [export_m4b(renderer, target, **options)]

        run_task(work, on_progress=self._export_progress, on_done=self._export_done,
                 on_failed=self._failed)  # fmt: skip

    def _export_progress(self, value) -> None:
        if isinstance(value, Renderer):
            self.renderer = value
            if problem := Metadata.from_book(value.book).cover_problem():
                self.export_status.setText(problem)
        elif isinstance(value, tuple):
            step, fraction = value
            self.export_progress.setValue(round(fraction * 100))
            self.export_status.setText(self.tr(step))

    def _export_done(self, result) -> None:
        self._end()
        if isinstance(result, int):
            self.export_status.setText(
                self.tr("%n paragraph(s) changed or aren't rendered yet. Press Render first.",
                        "", result)
            )  # fmt: skip
            return
        self.export_progress.setValue(100)
        where = result[0] if len(result) == 1 else result[0].parent
        self.export_status.setText(self.tr("Done: %1").replace("%1", str(where)))
        if self.free_cache.isChecked():
            self.renderer = None  # its audio is gone; a re-export renders again

    def _failed(self, exc: BaseException) -> None:
        self._end()
        if isinstance(exc, _NeedsDownload):
            self.download_voice(exc.voice)
            return
        if isinstance(exc, Cancelled):
            kept = getattr(exc, "written", [])
            self.export_status.setText(
                self.tr("Stopped. %n finished chapter file(s) were kept.", "", len(kept))
                if kept
                else self.tr("Stopped. No audiobook file was written.")
            )
            return
        log.error("Work failed", exc_info=exc)
        if isinstance(exc, FfmpegError | LookupError):
            message = (
                str(exc)
                if isinstance(exc, FfmpegError)
                else self.tr("Some rendered audio is missing. Press Render, then export again.")
            )
        else:
            message = self.tr("Something went wrong: %1. Details are in the log.").replace(
                "%1", str(exc) or type(exc).__name__
            )
        self.status.setText(message)
        QMessageBox.warning(self, self.tr("PageVoice"), message)

    # --- first run ---

    def download_voice(self, voice: VoiceSetup) -> None:
        """The first-run download (SPEC §2): the only time PageVoice goes online."""
        size = (voice.model_entry.size + voice.voice_entry.size) / 2**20
        answer = QMessageBox.question(
            self,
            self.tr("Download the voice"),
            self.tr(
                "PageVoice needs to download its voice once (about %1 MB). After that it "
                "works without the internet. Download it now?"
            ).replace("%1", f"{size:.0f}"),
        )
        if answer != QMessageBox.Yes:
            return
        dialog = QProgressDialog(self.tr("Downloading the voice…"), self.tr("Cancel"), 0, 100, self)
        dialog.setMinimumDuration(0)
        cancelled = threading.Event()
        dialog.canceled.connect(cancelled.set)
        started = time.monotonic()

        def work(report):
            def progress(done: int, total: int) -> None:
                if cancelled.is_set():
                    raise _Stopped
                report((done, total))

            voice.download(progress, use_source=voice.manifest.is_proposed)

        def on_progress(value) -> None:
            done, total = value
            dialog.setValue(round(done * 100 / max(1, total)))
            rate = done / max(0.001, time.monotonic() - started)
            dialog.setLabelText(
                self.tr("Downloading the voice… %1 of %2 MB").replace("%1", f"{done / 2**20:.0f}")
                .replace("%2", f"{total / 2**20:.0f}")
                + (f" ({duration_text((total - done) / rate)} left)" if rate else "")
            )  # fmt: skip

        def on_done(_result) -> None:
            dialog.close()
            self.start_render()

        def on_failed(exc) -> None:
            dialog.close()
            if isinstance(exc, _Stopped):
                return
            log.error("Voice download failed", exc_info=exc)
            QMessageBox.warning(
                self,
                self.tr("Download the voice"),
                self.tr(
                    "The voice couldn't be downloaded: %1. Check the internet connection and "
                    "try again."
                ).replace("%1", str(exc)),
            )

        run_task(work, on_progress=on_progress, on_done=on_done, on_failed=on_failed)


class _NeedsDownload(Exception):
    def __init__(self, voice: VoiceSetup) -> None:
        super().__init__("The voice isn't downloaded yet.")
        self.voice = voice
