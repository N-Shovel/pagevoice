"""Listen (D36): playing a chapter's rendered audio, with pause, seek and stop."""

import threading
import time

import numpy as np
import pytest

from pagevoice.render.cache import RenderCache
from pagevoice.render.playback import ChapterPlayer, PlaybackUnavailable
from pagevoice.render.renderer import Renderer
from pagevoice.voice.kokoro import SAMPLE_RATE
from pagevoice.voice.manifest import PROPOSED, load_manifest
from tests.test_render import FakeVoice, book


class FakeStream:
    """Stands in for the sound card: keeps what was written."""

    def __init__(self, delay: float = 0.0) -> None:
        self.written: list[np.ndarray] = []
        self.running = False
        self.delay = delay

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def close(self):
        pass

    def write(self, block):
        assert self.running, "written while stopped"
        self.written.append(block.copy())
        time.sleep(self.delay)

    @property
    def frames(self) -> int:
        return sum(len(b) for b in self.written)


@pytest.fixture
def renderer(tmp_path):
    voice = FakeVoice(manifest=load_manifest(PROPOSED))
    r = Renderer(book("First paragraph here.", "Second one.", "Third and last."), voice,
                 RenderCache(tmp_path / "cache"), book_id="listen")  # fmt: skip
    r.run()
    return r


def play(renderer, stream, **kwargs):
    ended = []
    player = ChapterPlayer(renderer, 0, on_end=ended.append, stream_factory=lambda: stream,
                           **kwargs)  # fmt: skip
    player.play()
    return player, ended


def test_timeline_reads_lengths_without_loading_audio(renderer, monkeypatch):
    monkeypatch.setattr(renderer.cache, "get", lambda key: pytest.fail("loaded audio"))
    timeline = renderer.timeline(0)
    assert [s.item.source for s in timeline][1:] == ["First paragraph here.", "Second one.",
                                                     "Third and last."]  # fmt: skip
    assert all(s.frames and s.frames > 0 for s in timeline)
    assert timeline[0].pause == int(renderer.settings.heading_pause * SAMPLE_RATE)


def test_plays_the_whole_chapter_with_pauses(renderer):
    stream = FakeStream()
    player, ended = play(renderer, stream)
    player.wait(5)
    assert ended == ["finished"]
    expected = sum(s.frames + s.pause for s in renderer.timeline(0))
    assert stream.frames == expected == round(player.total_seconds * SAMPLE_RATE)


def test_starts_from_a_paragraph_of_the_book(renderer):
    """Right-click "Listen from here" in review gives a book paragraph index."""
    second = renderer.first_at(0, 2)  # chapter.paragraphs[2] is "Second one."
    assert renderer.timeline(0)[second].item.source == "Second one."
    stream = FakeStream()
    player, _ended = play(renderer, stream, start=second)
    player.wait(5)
    rest = sum(s.frames + s.pause for s in renderer.timeline(0)[second:])
    assert stream.frames == rest


def test_pause_resume_stop(renderer):
    stream = FakeStream(delay=0.01)
    positions = []
    player, ended = play(renderer, stream, on_position=positions.append)
    while not positions:
        time.sleep(0.01)
    player.pause()
    time.sleep(0.15)
    paused_at = stream.frames
    time.sleep(0.2)
    assert stream.frames == paused_at and player.paused  # nothing written while paused
    player.play()
    while stream.frames == paused_at:
        time.sleep(0.01)
    player.stop()
    player.wait(5)
    assert ended == ["stopped"]
    assert positions[-1].seconds <= positions[-1].total


def test_seek_jumps(renderer):
    stream = FakeStream(delay=0.005)
    positions = []
    player, ended = play(renderer, stream, on_position=positions.append)
    player.pause()
    last = renderer.timeline(0)[-1]
    target = player.seconds_at(len(renderer.timeline(0)) - 1)
    player.seek(target)
    player.play()
    player.wait(5)
    assert ended == ["finished"]
    assert any(p.segment == len(renderer.timeline(0)) - 1 for p in positions)
    assert stream.frames < sum(s.frames + s.pause for s in renderer.timeline(0))
    assert last.frames


def test_stops_where_rendering_stopped(tmp_path):
    voice = FakeVoice(manifest=load_manifest(PROPOSED))
    r = Renderer(book("One.", "Two.", "Three."), voice, RenderCache(tmp_path / "c"), book_id="b")
    stop = threading.Event()
    rendered = []

    def progress(p):
        rendered.append(p)
        if len(rendered) == 2:
            stop.set()  # heading and "One." rendered, the rest not

    r.run(progress, stop=stop)
    stream = FakeStream()
    player, ended = play(r, stream)
    player.wait(5)
    assert ended == ["not rendered"]
    assert stream.frames == sum(s.frames + s.pause for s in r.timeline(0)[:2])


def test_waits_for_a_running_render(tmp_path):
    voice = FakeVoice(manifest=load_manifest(PROPOSED))
    r = Renderer(book("One.", "Two."), voice, RenderCache(tmp_path / "c"), book_id="b")
    rendering = threading.Event()
    rendering.set()
    stream = FakeStream()
    player, ended = play(r, stream, wait_for_render=rendering.is_set)
    time.sleep(0.3)
    assert stream.frames == 0 and not ended  # waiting, not given up
    r.run()
    rendering.clear()
    player.wait(5)
    assert ended == ["finished"] and stream.frames > 0


def test_no_sound_output_is_a_plain_message(renderer):
    def missing():
        raise PlaybackUnavailable("No sound output was found on this computer.")

    ended = []
    player = ChapterPlayer(renderer, 0, on_end=ended.append, stream_factory=missing)
    player.play()
    player.wait(5)
    assert ended == ["No sound output was found on this computer."]


def test_packaged_linux_build_uses_its_own_portaudio(tmp_path, monkeypatch):
    """CI found it: in a packaged Linux build, sounddevice searched the system for
    PortAudio, never the app's folder, so a machine without libportaudio2 had no sound."""
    import sys

    from pagevoice.render import playback

    (tmp_path / "libportaudio.so.2").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert playback.bundled_portaudio() == tmp_path / "libportaudio.so.2"
    monkeypatch.setattr(sys, "platform", "win32")  # Windows wheels carry their own
    assert playback.bundled_portaudio() is None
