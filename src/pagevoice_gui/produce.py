"""Voice, render and export (SPEC §6, §8): pick the voice, render with progress, pause and
resume (also after a restart, through the render cache), then write the M4B or MP3s."""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, Qt, Signal
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
from pagevoice.voice.download import ChecksumError
from pagevoice.voice.engine import DEFAULT_VOICE, VoiceSetup
from pagevoice_gui.session import Session
from pagevoice_gui.tasks import run_task

log = logging.getLogger(__name__)

VoiceFactory = Callable[[str, str], VoiceSetup]  # (voice name, "cpu" or "dml") -> voice


class VoiceUnavailable(RuntimeError):
    """The voice can't be set up at all (e.g. no manifest in this build). Plain message."""


def _t(text: str) -> str:
    return QCoreApplication.translate("ProducePage", text)


def voice_label(name: str) -> str:
    """'af_heart' -> 'Heart (American, female)'."""
    accents = {"a": _t("American"), "b": _t("British")}
    genders = {"f": _t("female"), "m": _t("male")}
    prefix, _, rest = name.partition("_")
    if len(prefix) == 2 and prefix[0] in accents and prefix[1] in genders:
        return f"{rest.title()} ({accents[prefix[0]]}, {genders[prefix[1]]})"
    return name


def duration_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return _t("under a minute")
    hours, minutes = divmod(minutes, 60)
    if hours:
        return _t("%1 h %2 min").replace("%1", str(hours)).replace("%2", str(minutes))
    return _t("%1 min").replace("%1", str(minutes))


class _NeedsDownload(Exception):
    def __init__(self, voice: VoiceSetup) -> None:
        super().__init__("The voice isn't downloaded yet.")
        self.voice = voice


class _Stopped(Exception):
    """The user cancelled the download."""


class _Planned:
    """The render plan, with its counts worked out on the worker (cache lookups)."""

    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.total = len(renderer.items)
        self.done = self.total - len(renderer.pending())


class ProducePage(QWidget):
    review_clicked = Signal()
    pronunciations_clicked = Signal()
    busy_changed = Signal(bool)  # the main window locks review edits while work runs
    notes_setting_changed = Signal()

    def __init__(
        self,
        voice_factory: VoiceFactory,
        voices: list[str],
        cache: RenderCache,
        parent=None,
        *,
        dml: bool = False,
        allow_upstream_download: bool = False,
    ) -> None:
        super().__init__(parent)
        self.voice_factory, self.cache = voice_factory, cache
        self.allow_upstream_download = allow_upstream_download  # dev runs only (D9)
        self.session: Session | None = None
        self.renderer: Renderer | None = None
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.settings = QSettings()
        self._busy = self._rendering = False
        self._download_cancelled = threading.Event()
        self.step_names = {"Preparing chapters": self.tr("Preparing chapters"),
                           "Encoding": self.tr("Encoding")}  # fmt: skip

        # Voice
        self.voice = QComboBox()
        for name in voices:
            self.voice.addItem(voice_label(name), name)
        self.voice.setCurrentIndex(
            max(0, self.voice.findData(self.settings.value("voice", DEFAULT_VOICE)))
        )
        self.voice.setMaximumWidth(360)
        self.speed = QDoubleSpinBox(minimum=0.5, maximum=2.0, singleStep=0.05, decimals=2)
        self.speed.setValue(float(self.settings.value("speed", 1.0)))
        self.speed.setSuffix(" ×")
        self.speed.setMaximumWidth(120)
        self.read_notes = QCheckBox(self.tr("Read footnotes at the end of each chapter"))
        self.read_notes.setChecked(self.settings.value("read_notes", True, type=bool))
        self.use_gpu = QCheckBox(self.tr("Use the graphics card (DirectML)"))
        self.use_gpu.setChecked(dml and self.settings.value("use_gpu", False, type=bool))
        self.use_gpu.setVisible(dml)
        self.voice.currentIndexChanged.connect(self._settings_changed)
        self.speed.valueChanged.connect(self._settings_changed)
        self.read_notes.toggled.connect(self._settings_changed)
        self.read_notes.toggled.connect(lambda _on: self.notes_setting_changed.emit())
        self.use_gpu.toggled.connect(self._settings_changed)
        self.language = QLabel()
        voice_box = QGroupBox(self.tr("Voice"))
        form = QFormLayout(voice_box)
        form.addRow(self.tr("Voice:"), self.voice)
        form.addRow(self.tr("Speed:"), self.speed)
        form.addRow(self.tr("Language:"), self.language)
        form.addRow(self.read_notes)
        form.addRow(self.use_gpu)
        links = QHBoxLayout()
        # Buttons emit the page's signals through a lambda: PySide6 can't take a signal
        # instance as a slot ("native Qt signal instance is not callable").
        pronunciations = QPushButton(self.tr("Pronunciations…"))
        pronunciations.clicked.connect(lambda: self.pronunciations_clicked.emit())
        back = QPushButton(self.tr("Back to review"))
        back.clicked.connect(lambda: self.review_clicked.emit())
        links.addWidget(pronunciations)
        links.addWidget(back)
        links.addStretch()
        form.addRow(links)

        # Render
        self.render_button = QPushButton(self.tr("Render"), clicked=lambda: self.start_render())
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
        self.browse = QPushButton(self.tr("Choose…"), clicked=self.choose_target)
        self.export_button = QPushButton(self.tr("Export"), clicked=self.start_export)
        self.export_progress = QProgressBar()
        self.export_status = QLabel(wordWrap=True)
        self.free_button = QPushButton(
            self.tr("Free this book's rendered audio"), clicked=self.free_cache
        )
        self.free_button.setToolTip(self.tr(
            "The rendered audio is kept so that editing a few paragraphs later only re-renders "
            "those. Free it when you're done with this book."
        ))  # fmt: skip
        self.free_button.hide()
        export_box = QGroupBox(self.tr("Export"))
        export_layout = QVBoxLayout(export_box)
        export_layout.addWidget(self.m4b)
        export_layout.addWidget(self.mp3)
        target_row = QHBoxLayout()
        target_row.addWidget(self.target, 1)
        target_row.addWidget(self.browse)
        export_layout.addLayout(target_row)
        export_layout.addWidget(self.export_button)
        export_layout.addWidget(self.export_progress)
        export_layout.addWidget(self.export_status)
        export_layout.addWidget(self.free_button)

        layout = QVBoxLayout(self)
        layout.addWidget(voice_box)
        layout.addWidget(render_box)
        layout.addWidget(export_box)
        layout.addStretch()
        self._update_buttons()

    # --- book and settings ---

    def set_session(self, session: Session) -> None:
        self.session = session
        session.edited.connect(self.plan_changed)
        self.renderer = None
        self.language.setText(session.book.language)
        self._default_target()
        self.status.setText(self.tr("Ready. Rendering resumes where it stopped, even after a "
                                    "restart."))  # fmt: skip
        self.current.clear()
        self.problems.clear()
        self.problems.hide()
        self.progress.setValue(0)
        self.export_progress.setValue(0)
        self.export_status.clear()
        self.free_button.hide()
        self._update_buttons()

    def plan_changed(self) -> None:
        """Review, pronunciation or voice settings changed: the next render or export
        works out again which paragraphs need audio (changed ones only)."""
        self.renderer = None

    def _settings_changed(self, *_args) -> None:
        self.settings.setValue("voice", self.voice.currentData())
        self.settings.setValue("speed", self.speed.value())
        self.settings.setValue("read_notes", self.read_notes.isChecked())
        self.settings.setValue("use_gpu", self.use_gpu.isChecked())
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
        for widget in (self.render_button, self.export_button, self.voice, self.speed,
                       self.read_notes, self.use_gpu, self.m4b, self.mp3, self.target,
                       self.browse, self.free_button):  # fmt: skip
            widget.setEnabled(idle)
        self.pause_button.setEnabled(self._busy and self._rendering)
        self.stop_button.setEnabled(self._busy)

    @property
    def busy(self) -> bool:
        return self._busy

    # --- work ---

    def _planner(self) -> Callable[[Callable], _Planned]:
        """Read the settings here, on the UI thread. The returned function runs on a
        worker: it checks the voice files (hashing ~300 MB once) and plans the render."""
        existing = self.renderer
        voice_name, speed = self.voice.currentData(), self.speed.value()
        provider = "dml" if self.use_gpu.isChecked() else "cpu"
        drop_notes = not self.read_notes.isChecked()
        session, cache, factory = self.session, self.cache, self.voice_factory
        checking, preparing = self.tr("Checking the voice files…"), self.tr("Preparing the text…")

        def plan(report) -> _Planned:
            if existing is not None:
                return _Planned(existing)
            report(checking)
            voice = factory(voice_name, provider)
            if not voice.ready():
                raise _NeedsDownload(voice)
            report(preparing)
            with session.lock:
                renderer = Renderer(
                    session.book,
                    voice,
                    cache,
                    book_id=session.book_id,
                    settings=RenderSettings(speed=speed, drop_notes=drop_notes),
                    pronunciations=entries_for(session.pronunciations_path),
                )
            return _Planned(renderer)

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
            planned = plan(report)
            report(planned)
            return planned.renderer.run(report, stop=self.stop, pause=self.pause)

        run_task(work, on_progress=self._render_progress, on_done=self._render_done,
                 on_failed=lambda exc: self._failed(exc, retry=self.start_render))  # fmt: skip

    def _render_progress(self, value) -> None:
        if isinstance(value, str):
            self.status.setText(value)
        elif isinstance(value, _Planned):
            self.renderer = value.renderer
            self.progress.setMaximum(max(1, value.total))
            self.progress.setValue(value.done)
            message = self.tr("%1 of %2 paragraphs already rendered. Rendering the rest…")
            self.status.setText(message.replace("%1", f"{value.done:,}")
                                .replace("%2", f"{value.total:,}"))  # fmt: skip
        elif isinstance(value, Progress):
            self.progress.setMaximum(max(1, value.total))
            self.progress.setValue(value.done)
            parts = [self.tr("%1 of %2 paragraphs").replace("%1", f"{value.done:,}")
                     .replace("%2", f"{value.total:,}")]  # fmt: skip
            if value.eta_seconds is not None:
                left = self.tr("about %1 left")
                parts.append(left.replace("%1", duration_text(value.eta_seconds)))
            if value.elapsed > 0:
                speed = value.audio_seconds / value.elapsed
                parts.append(self.tr("%1× real time").replace("%1", f"{speed:.1f}"))
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
            self.status.setText(self.tr("%n paragraph(s) failed. Press Render to try them again.",
                                        "", len(result.failed)))  # fmt: skip
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
        self._download_cancelled.set()

    def start_export(self) -> None:
        text = self.target.text().strip()
        if not text:
            self.choose_target()
            return
        target = Path(text)
        plan = self._planner()
        self._begin(rendering=False)
        self.free_button.hide()
        as_mp3 = self.mp3.isChecked()
        self.export_status.setText(self.tr("Checking that everything is rendered…"))

        def work(report):
            planned = plan(lambda _msg: None)
            report(planned)
            if planned.done < planned.total:
                return planned.total - planned.done
            renderer = planned.renderer
            options = dict(
                meta=Metadata.from_book(renderer.book),
                progress=lambda step, fraction: report((step, fraction)),
                stop=self.stop,
                clear_cache=False,  # kept: the user frees it when done editing (D34)
            )
            if as_mp3:
                return export_mp3(renderer, target, **options)
            return [export_m4b(renderer, target, **options)]

        run_task(work, on_progress=self._export_progress, on_done=self._export_done,
                 on_failed=lambda exc: self._failed(exc, retry=self.start_export))  # fmt: skip

    def _export_progress(self, value) -> None:
        if isinstance(value, _Planned):
            self.renderer = value.renderer
            if problem := Metadata.from_book(value.renderer.book).cover_problem():
                self.export_status.setText(problem)
        elif isinstance(value, tuple):
            step, fraction = value
            self.export_progress.setValue(round(fraction * 100))
            self.export_status.setText(self.step_names.get(step, step))

    def _export_done(self, result) -> None:
        self._end()
        if isinstance(result, int):
            self.export_status.setText(self.tr(
                "%n paragraph(s) changed or aren't rendered yet. Press Render first.", "", result
            ))  # fmt: skip
            return
        self.export_progress.setValue(100)
        where = result[0] if len(result) == 1 else result[0].parent
        self.export_status.setText(self.tr("Done: %1").replace("%1", str(where)))
        self.free_button.show()

    def free_cache(self) -> None:
        """Free the book's rendered audio (D26): a later export renders it again."""
        cache, book_id = self.cache, self.session.book_id
        self.free_button.setEnabled(False)

        def done(freed: int) -> None:
            self.renderer = None
            self.free_button.hide()
            self.free_button.setEnabled(True)
            self.export_status.setText(self.tr("Freed %1 MB of rendered audio.")
                                       .replace("%1", f"{freed / 2**20:,.0f}"))  # fmt: skip

        run_task(lambda _r: cache.clear_book(book_id), on_done=done,
                 on_failed=lambda exc: self._failed(exc))  # fmt: skip

    def _failed(self, exc: BaseException, retry: Callable[[], None] | None = None) -> None:
        self._end()
        if isinstance(exc, _NeedsDownload):
            self.download_voice(exc.voice, then=retry)
            return
        if isinstance(exc, Cancelled):
            kept = getattr(exc, "written", [])
            self.export_status.setText(
                self.tr("Stopped. %n finished chapter file(s) were kept.", "", len(kept))
                if kept
                else self.tr("Stopped. No audiobook file was written.")
            )
            return
        if isinstance(exc, VoiceUnavailable | FfmpegError):
            message = str(exc)  # already plain language
        elif isinstance(exc, LookupError):
            message = self.tr("Some rendered audio is missing. Press Render, then export again.")
        else:
            log.error("Work failed", exc_info=exc)
            message = self.tr("Something went wrong: %1. Details are in the log.").replace(
                "%1", str(exc) or type(exc).__name__
            )
        self.status.setText(message)
        QMessageBox.warning(self, self.tr("PageVoice"), message)

    # --- first run ---

    def download_voice(self, voice: VoiceSetup, then: Callable[[], None] | None = None) -> None:
        """The first-run download (SPEC §2): the only time PageVoice goes online. Files
        come from our release and are checked against the manifest (D9)."""
        size = (voice.model_entry.size + voice.voice_entry.size) / 2**20
        answer = QMessageBox.question(
            self,
            self.tr("Download the voice"),
            self.tr("PageVoice needs to download its voice once (about %1 MB). After that it "
                    "works without the internet. Download it now?").replace("%1", f"{size:.0f}"),
        )  # fmt: skip
        if answer != QMessageBox.Yes:
            return
        self._begin(rendering=False)
        self._download_cancelled.clear()
        dialog = QProgressDialog(self.tr("Downloading the voice…"), self.tr("Cancel"), 0, 100, self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(self._download_cancelled.set)
        cancelled, started = self._download_cancelled, time.monotonic()
        use_source = voice.manifest.is_proposed and self.allow_upstream_download

        def work(report):
            def progress(done: int, total: int) -> None:
                if cancelled.is_set():
                    raise _Stopped
                report((done, total))

            voice.download(progress, use_source=use_source)

        def on_progress(value) -> None:
            done, total = value
            dialog.setValue(round(done * 100 / max(1, total)))
            rate = done / max(0.001, time.monotonic() - started)
            label = self.tr("Downloading the voice… %1 of %2 MB").replace(
                "%1", f"{done / 2**20:.0f}").replace("%2", f"{total / 2**20:.0f}")  # fmt: skip
            if rate:
                label += " " + self.tr("(%1 left)").replace(
                    "%1", duration_text((total - done) / rate))  # fmt: skip
            dialog.setLabelText(label)

        def on_done(_result) -> None:
            dialog.close()
            self._end()
            if then is not None:
                then()

        def on_failed(exc) -> None:
            dialog.close()
            self._end()
            if isinstance(exc, _Stopped):
                return
            log.error("Voice download failed", exc_info=exc)
            if isinstance(exc, ChecksumError):
                message = self.tr("The download was damaged, so it was deleted. Please try again.")
            else:
                message = self.tr("The voice couldn't be downloaded. Check the internet "
                                  "connection and try again.")  # fmt: skip
            QMessageBox.warning(self, self.tr("Download the voice"), message)

        run_task(work, on_progress=on_progress, on_done=on_done, on_failed=on_failed)
