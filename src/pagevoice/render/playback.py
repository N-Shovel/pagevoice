"""Play a chapter's rendered audio through the sound card (the Listen feature, D36).

The chapter is a timeline of cached paragraphs with their pauses. Playback runs on its
own thread and writes the audio to the output in small blocks, so pause, seek and stop
take effect within about a tenth of a second. Paragraphs not rendered yet are waited for
while a render is running (wait_for_render), otherwise playback ends there.

sounddevice (the gui extra) is imported only when a stream is opened; the output stream
can be replaced in tests.
"""

import ctypes.util
import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pagevoice.render.renderer import Renderer, Segment
from pagevoice.voice.kokoro import SAMPLE_RATE

log = logging.getLogger(__name__)

BLOCK = SAMPLE_RATE // 10  # frames written at a time: controls react within 0.1 s


class PlaybackUnavailable(RuntimeError):
    """No way to play sound on this computer. The message is plain language."""


@dataclass
class Position:
    segment: int  # index in the timeline
    seconds: float  # from the start of the chapter
    total: float  # chapter length so far known (rendered paragraphs and pauses)


def bundled_portaudio() -> Path | None:
    """PortAudio inside a packaged Linux build (Windows wheels carry their own copy)."""
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not bundle or sys.platform == "win32":
        return None
    return next(iter(sorted(Path(bundle).glob("libportaudio.so*"))), None)


def import_sounddevice():
    """Import sounddevice, finding the bundled PortAudio in a packaged Linux build.

    sounddevice looks for PortAudio with ctypes.util.find_library, which searches the
    system, never the app's own folder; on a machine without libportaudio2 it would fail.
    """
    bundled = bundled_portaudio()
    if bundled is None:
        import sounddevice

        return sounddevice
    system_find = ctypes.util.find_library

    def find(name: str):
        return str(bundled) if name == "portaudio" else system_find(name)

    ctypes.util.find_library = find
    try:
        import sounddevice
    finally:
        ctypes.util.find_library = system_find
    return sounddevice


def open_stream():
    """The default sound output, mono at Kokoro's rate."""
    try:
        sounddevice = import_sounddevice()
    except (ImportError, OSError) as exc:  # Linux without libportaudio2, for example
        raise PlaybackUnavailable(
            "Sound can't be played here: the audio library (PortAudio) is missing."
        ) from exc
    try:
        stream = sounddevice.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    except Exception as exc:
        raise PlaybackUnavailable("No sound output was found on this computer.") from exc
    return stream


class ChapterPlayer:
    """Plays one chapter from a paragraph, on its own thread.

    on_position(Position) is called about ten times a second; on_end(reason) once, with
    "finished", "stopped" or "not rendered" (the next paragraph isn't rendered and no
    render is running). Both are called on the playback thread."""

    def __init__(
        self,
        renderer: Renderer,
        chapter: int,
        *,
        start: int = 0,
        on_position: Callable[[Position], None] | None = None,
        on_end: Callable[[str], None] | None = None,
        wait_for_render: Callable[[], bool] = lambda: False,
        stream_factory: Callable = open_stream,
    ) -> None:
        self.renderer, self.chapter = renderer, chapter
        self.timeline: list[Segment] = renderer.timeline(chapter)
        self.on_position, self.on_end = on_position, on_end
        self.wait_for_render, self.stream_factory = wait_for_render, stream_factory
        self._segment, self._offset = min(start, max(0, len(self.timeline) - 1)), 0
        self._paused = threading.Event()
        self._stopped = threading.Event()
        self._seek: float | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- timeline arithmetic ---

    def _lengths(self) -> list[int]:
        return [(s.frames or 0) + s.pause for s in self.timeline]

    def seconds_at(self, segment: int, offset: int = 0) -> float:
        return (sum(self._lengths()[:segment]) + offset) / SAMPLE_RATE

    @property
    def total_seconds(self) -> float:
        return sum(self._lengths()) / SAMPLE_RATE

    def _locate(self, seconds: float) -> tuple[int, int]:
        frame = max(0, int(seconds * SAMPLE_RATE))
        for n, length in enumerate(self._lengths()):
            if frame < length:
                return n, frame
            frame -= length
        return max(0, len(self.timeline) - 1), 0

    # --- controls (any thread) ---

    def play(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="playback", daemon=True)
            self._thread.start()
        self._paused.clear()

    def pause(self) -> None:
        self._paused.set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def seek(self, seconds: float) -> None:
        with self._lock:
            self._seek = seconds

    def stop(self) -> None:
        self._stopped.set()
        self._paused.clear()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- the playback thread ---

    def _audio(self, segment: Segment) -> np.ndarray | None:
        if segment.frames is None:  # rendered since the timeline was made?
            frames = self.renderer.cache.frames(segment.item.key)
            if frames is None:
                return None
            segment = self.timeline[self._segment] = Segment(segment.item, frames, segment.pause)
        audio = self.renderer.cache.get(segment.item.key)
        if audio is None:
            return None
        silence = np.zeros(segment.pause, dtype=np.float32)
        return np.concatenate([np.asarray(audio, dtype=np.float32), silence])

    def _run(self) -> None:
        reason = "finished"
        try:
            stream = self.stream_factory()
        except PlaybackUnavailable as exc:
            log.warning("%s", exc)
            self._end(str(exc))
            return
        try:
            stream.start()
            reason = self._loop(stream)
        except Exception:
            log.exception("Playback failed")
            reason = "failed"
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("Closing the sound output failed", exc_info=True)
        self._end(reason)

    def _loop(self, stream) -> str:
        while self._segment < len(self.timeline):
            audio = self._audio(self.timeline[self._segment])
            if audio is None:
                if self.wait_for_render() and not self._stopped.is_set():
                    time.sleep(0.2)  # the render will get there
                    continue
                return "not rendered"
            while self._offset < len(audio):
                if self._stopped.is_set():
                    return "stopped"
                with self._lock:
                    seek, self._seek = self._seek, None
                if seek is not None:
                    self._segment, self._offset = self._locate(seek)
                    break  # load the segment sought to
                if self._paused.is_set():
                    stream.stop()
                    while self._paused.is_set() and not self._stopped.is_set():
                        time.sleep(0.05)
                    if not self._stopped.is_set():
                        stream.start()
                    continue
                block = audio[self._offset : self._offset + BLOCK]
                stream.write(block.reshape(-1, 1))
                self._offset += len(block)
                if self.on_position:
                    self.on_position(
                        Position(
                            self._segment,
                            self.seconds_at(self._segment, self._offset),
                            self.total_seconds,
                        )  # fmt: skip
                    )
            else:
                self._segment, self._offset = self._segment + 1, 0
        return "stopped" if self._stopped.is_set() else "finished"

    def _end(self, reason: str) -> None:
        if self.on_end:
            self.on_end(reason)
