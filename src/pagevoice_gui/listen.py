"""The Listen bar (D36): hear rendered chapters in the app before exporting.

The engine's ChapterPlayer plays on its own thread; its updates are relayed to the UI
thread through Qt signals. The bar needs a render plan (which paragraph has which audio),
which the voice page makes on a worker, as it does for a render."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pagevoice.render.playback import ChapterPlayer, Position
from pagevoice.render.renderer import Renderer

log = logging.getLogger(__name__)


def clock(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


class _Relay(QObject):
    """Lives on the UI thread; the playback thread emits, Qt queues the calls here."""

    position = Signal(object)  # (player, Position)
    ended = Signal(object)  # (player, reason)


class ListenBar(QWidget):
    """Chapter, play/pause, stop, a seek slider, the time and what's being read."""

    def __init__(
        self,
        get_renderer: Callable[[Callable[[Renderer], None]], None],
        is_rendering: Callable[[], bool],
        parent=None,
        *,
        stream_factory=None,
    ) -> None:
        super().__init__(parent)
        self.get_renderer, self.is_rendering = get_renderer, is_rendering
        self.stream_factory = stream_factory  # tests replace the sound card
        self.player: ChapterPlayer | None = None
        self._dragging = False
        self.relay = _Relay()
        self.relay.position.connect(self._position)
        self.relay.ended.connect(self._ended)

        self.chapter = QComboBox()
        self.chapter.setMinimumWidth(220)
        self.play_button = QPushButton(self.tr("▶ Play"))
        self.play_button.clicked.connect(lambda: self.toggle())
        self.stop_button = QPushButton(self.tr("■ Stop"), enabled=False)
        self.stop_button.clicked.connect(lambda: self.stop())
        self.slider = QSlider(Qt.Horizontal, enabled=False)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._seek)
        self.time = QLabel("0:00 / 0:00")
        self.reading = QLabel(wordWrap=False)
        self.reading.setStyleSheet("color:#777;")
        self.reading.setTextInteractionFlags(Qt.NoTextInteraction)

        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Listen:")))
        row.addWidget(self.chapter)
        row.addWidget(self.play_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.slider, 1)
        row.addWidget(self.time)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.reading)

    def set_chapters(self, titles: list[str], select: int = 0) -> None:
        self.stop()
        self.chapter.clear()
        for number, title in enumerate(titles, 1):
            self.chapter.addItem(f"{number}. {title}")
        self.chapter.setCurrentIndex(max(0, min(select, len(titles) - 1)))

    # --- controls ---

    def toggle(self) -> None:
        if self.player is not None:
            if self.player.paused:
                self.player.play()
                self.play_button.setText(self.tr("⏸ Pause"))
            else:
                self.player.pause()
                self.play_button.setText(self.tr("▶ Play"))
            return
        self.play_from(self.chapter.currentIndex(), None)

    def play_from(self, chapter: int, position: int | None) -> None:
        """Play a chapter from its start, or from a paragraph of the book (review)."""
        self.stop()
        if chapter < 0:
            return
        self.chapter.setCurrentIndex(chapter)
        self.reading.setText(self.tr("Getting ready…"))
        self.play_button.setEnabled(False)

        def start(renderer: Renderer) -> None:
            self.play_button.setEnabled(True)
            start_at = renderer.first_at(chapter, position) if position is not None else 0
            options = {"stream_factory": self.stream_factory} if self.stream_factory else {}
            player = ChapterPlayer(
                renderer, chapter, start=start_at, wait_for_render=self.is_rendering, **options
            )
            # Updates carry their player: a stopped one's late "ended" can't reset the next.
            player.on_position = lambda pos: self.relay.position.emit((player, pos))
            player.on_end = lambda reason: self.relay.ended.emit((player, reason))
            self.player = player
            if not self.player.timeline:
                self.player = None
                self.reading.setText(self.tr("This chapter has nothing to read."))
                return
            self.slider.setRange(0, int(self.player.total_seconds * 1000))
            self.slider.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.play_button.setText(self.tr("⏸ Pause"))
            self.player.play()

        def failed(message: str) -> None:
            self.play_button.setEnabled(True)
            self.reading.setText(message)

        self.get_renderer(start, failed)

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.player = None
        self.play_button.setText(self.tr("▶ Play"))
        self.stop_button.setEnabled(False)
        self.slider.setEnabled(False)

    def _seek(self) -> None:
        self._dragging = False
        if self.player is not None:
            self.player.seek(self.slider.value() / 1000)

    # --- from the playback thread, via the relay ---

    def _position(self, update: tuple[ChapterPlayer, Position]) -> None:
        player, position = update
        if player is not self.player:
            return
        self.slider.setMaximum(int(position.total * 1000))
        if not self._dragging:
            self.slider.setValue(int(position.seconds * 1000))
        self.time.setText(f"{clock(position.seconds)} / {clock(position.total)}")
        segment = player.timeline[position.segment]
        where = self.tr("Paragraph %1 of %2: ").replace("%1", str(position.segment + 1)).replace(
            "%2", str(len(player.timeline)))  # fmt: skip
        text = segment.item.source
        self.reading.setText(where + (text[:140] + "…" if len(text) > 140 else text))

    def _ended(self, update: tuple[ChapterPlayer, str]) -> None:
        player, reason = update
        if player is not self.player:
            return
        if reason == "finished":
            self.reading.setText(self.tr("End of the chapter."))
        elif reason == "not rendered":
            self.reading.setText(self.tr(
                "That's as far as this chapter is rendered. Press Render to do the rest."
            ))  # fmt: skip
        elif reason == "stopped":
            pass
        elif reason == "failed":
            self.reading.setText(self.tr("Playback stopped because of an error. Details are "
                                         "in the log."))  # fmt: skip
        else:  # a plain message from the engine, e.g. no sound output
            self.reading.setText(reason)
            QMessageBox.information(self, self.tr("Listen"), reason)
        self.player = None
        self.play_button.setText(self.tr("▶ Play"))
        self.stop_button.setEnabled(False)
        self.slider.setEnabled(False)
