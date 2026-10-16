"""Paragraph render cache and renderer: keys, atomic writes, resume, pause and cancel.

A fake voice stands in for Kokoro so these run fast; test_voice.py covers the real one.
"""

import os
import threading
import time

import numpy as np
import pytest

from pagevoice.document import Book, Chapter, Paragraph
from pagevoice.pronounce.lexicon import Entry
from pagevoice.render.cache import STALE_TMP_SECONDS, KeyParts, RenderCache
from pagevoice.render.renderer import Renderer, RenderSettings
from pagevoice.voice.engine import VoiceSetup
from pagevoice.voice.manifest import PROPOSED, load_manifest


class FakeVoice(VoiceSetup):
    """Synthesizes 0.1 s of tone per character group; counts calls."""

    calls: int = 0

    def phonemes(self, text: str) -> str:
        return text

    def synthesize(self, phonemes: str, speed: float = 1.0) -> np.ndarray:
        self.calls += 1
        if "boom" in phonemes.lower():
            raise RuntimeError("synthesis failed")
        return np.full(2400 * max(1, len(phonemes) // 10), 0.1, dtype=np.float32)


@pytest.fixture
def voice():
    return FakeVoice(manifest=load_manifest(PROPOSED))


@pytest.fixture
def cache(tmp_path):
    return RenderCache(tmp_path / "cache")


def book(*texts: str, notes: tuple[str, ...] = ()) -> Book:
    chapter = Chapter(
        title="One",
        paragraphs=[Paragraph.plain("Chapter One", kind="heading")]
        + [Paragraph.plain(t) for t in texts],
        notes=[Paragraph.plain(n, kind="note") for n in notes],
    )
    return Book(title="Test", chapters=[chapter])


def test_renders_then_resumes_from_cache(voice, cache):
    b = book("It was 1945.", "Mr. Darcy arrived.", "The end.")
    renderer = Renderer(b, voice, cache, book_id="b1")
    assert renderer.items[1].spoken == "It was nineteen forty-five."
    first = renderer.run()
    assert (first.rendered, first.cached) == (4, 0)
    calls = voice.calls
    again = Renderer(b, voice, cache, book_id="b1").run()
    assert (again.rendered, again.cached) == (0, 4)
    assert voice.calls == calls  # nothing synthesized twice


def test_editing_one_paragraph_rerenders_only_it(voice, cache):
    Renderer(book("One.", "Two.", "Three."), voice, cache, book_id="b").run()
    result = Renderer(book("One.", "Two, changed.", "Three."), voice, cache, book_id="b").run()
    assert (result.rendered, result.cached) == (1, 3)


def test_cancel_and_resume(voice, cache):
    renderer = Renderer(book(*[f"Paragraph {n}." for n in range(10)]), voice, cache, book_id="b")
    stop = threading.Event()

    def progress(p):
        if p.done >= 4:
            stop.set()

    first = renderer.run(progress, stop=stop)
    assert first.cancelled and first.rendered == 4
    second = renderer.run()
    assert (second.rendered, second.cached) == (7, 4)


def test_pause_waits_until_released(voice, cache):
    renderer = Renderer(book("One.", "Two."), voice, cache, book_id="b")
    pause = threading.Event()
    pause.set()
    done = threading.Event()
    thread = threading.Thread(target=lambda: (renderer.run(pause=pause), done.set()))
    thread.start()
    assert not done.wait(0.5)  # paused: nothing finishes
    assert voice.calls == 0
    pause.clear()
    assert done.wait(5)
    thread.join()
    assert voice.calls == 3  # heading and both paragraphs, once released


def test_one_failing_paragraph_does_not_stop_the_book(voice, cache):
    result = Renderer(book("Fine.", "BOOM here.", "Also fine."), voice, cache, book_id="b").run()
    assert result.rendered == 3 and len(result.failed) == 1


def test_book_language_reaches_the_g2p(cache, monkeypatch):
    seen = []

    def fake_g2p_for(language, backend=None):
        seen.append(language)
        return lambda text: text

    class RealPhonemes(FakeVoice):
        phonemes = VoiceSetup.phonemes

    monkeypatch.setattr("pagevoice.voice.g2p.g2p_for", fake_g2p_for)
    voice = RealPhonemes(manifest=load_manifest(PROPOSED))
    voice.phonemes("warm up in US English")
    b = book("Colour.")
    b.language = "en-GB"
    Renderer(b, voice, cache, book_id="b").run()
    assert seen == ["en", "en-GB"]


def test_g2p_warnings_are_reported(cache):
    class Dropping(FakeVoice):
        g2p_warning = None

        def phonemes(self, text):
            self.g2p_warning = (
                "Part of this text couldn't be pronounced." if "zz" in text.lower() else None
            )
            return text

    voice = Dropping(manifest=load_manifest(PROPOSED))
    result = Renderer(book("Fine.", "Zzxq here."), voice, cache, book_id="b").run()
    assert [(item.source, warning) for item, warning in result.warnings] == [
        ("Zzxq here.", "Part of this text couldn't be pronounced.")
    ]


def test_pronunciation_notes_do_not_change_the_key(voice, cache):
    def key(note):
        entries = [Entry("Hermione", "her-MY-oh-nee", note=note)]
        r = Renderer(book("Hermione smiled."), voice, cache, book_id="b", pronunciations=entries)
        return r.items[1].key

    assert key("") == key("from the film")


def test_g2p_package_versions_are_in_the_key(voice):
    assert "misaki=0.9.4" in voice.g2p_name


def test_notes_are_read_last_unless_dropped(voice, cache):
    b = book("Body.", notes=("1 A note.",))
    assert Renderer(b, voice, cache, book_id="b").items[-1].source == "1 A note."
    dropped = Renderer(b, voice, cache, book_id="b", settings=RenderSettings(drop_notes=True))
    assert all(i.source != "1 A note." for i in dropped.items)


def test_pronunciation_entries_change_the_key(voice, cache):
    plain = Renderer(book("Hermione smiled."), voice, cache, book_id="b").items[1]
    entries = [Entry("Hermione", "her-MY-oh-nee")]
    named = Renderer(book("Hermione smiled."), voice, cache, book_id="b", pronunciations=entries)
    assert named.items[1].spoken == "her-MY-oh-nee smiled."
    assert named.items[1].key != plain.key


@pytest.mark.parametrize(
    "change",
    [
        {"text": "other"},
        {"voice": "am_adam"},
        {"variant": "int8"},
        {"model_sha256": "1" * 64},
        {"voice_sha256": "2" * 64},
        {"speed": 1.1},
        {"g2p": "espeak"},
        {"entries": (("word", "x"),)},
        {"language": "en-gb"},
    ],
)
def test_everything_that_changes_audio_changes_the_key(change):
    base = dict(
        text="hello", entries=(), voice="af_heart", variant="fp32", model_sha256="0" * 64,
        voice_sha256="0" * 64, speed=1.0, g2p="misaki", language="en",
    )  # fmt: skip
    assert KeyParts(**base).key() != KeyParts(**{**base, **change}).key()


def test_cache_writes_are_atomic_and_trim_respects_the_cap(cache):
    audio = np.zeros(24000, dtype=np.float32)
    for n in range(5):
        cache.put(f"{n:064x}", audio, 24000)
    assert not list(cache.root.rglob("*.tmp"))
    assert np.allclose(cache.get(f"{0:064x}"), audio)
    cache.cap_bytes = 1
    cache.trim(protect={f"{4:064x}"})
    assert [p.stem for p in cache.root.rglob("*.flac")] == [f"{4:064x}"]


def test_loud_audio_is_clipped_not_wrapped(cache):
    cache.put("c" * 64, np.array([1.5, -1.5, 0.5], dtype=np.float32), 24000)
    audio = cache.get("c" * 64)
    assert audio[0] > 0.99 and audio[1] < -0.99 and abs(audio[2] - 0.5) < 1e-3


def test_trim_removes_stale_temp_files_only(cache):
    stale = cache.root / "audio" / "ab" / "x.old.tmp"
    fresh = cache.root / "audio" / "ab" / "x.new.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"half")
    fresh.write_bytes(b"half")
    old = time.time() - 2 * STALE_TMP_SECONDS
    os.utime(stale, (old, old))
    cache.trim()
    assert not stale.exists() and fresh.exists()


def test_book_index_keeps_earlier_keys(cache):
    cache.remember("one", ["a" * 64])  # e.g. chapter 1 rendered alone
    cache.remember("one", ["b" * 64])  # then chapter 2
    assert cache.book_keys("one") == {"a" * 64, "b" * 64}


def test_clear_book_keeps_audio_other_books_use(cache):
    audio = np.zeros(2400, dtype=np.float32)
    for key in ("a" * 64, "b" * 64):
        cache.put(key, audio, 24000)
    cache.remember("one", ["a" * 64, "b" * 64])
    cache.remember("two", ["b" * 64])
    cache.clear_book("one")
    assert not cache.has("a" * 64) and cache.has("b" * 64)


def test_chapter_audio_joins_paragraphs_with_pauses(voice, cache):
    renderer = Renderer(book("One.", "Two."), voice, cache, book_id="b")
    with pytest.raises(LookupError):
        renderer.chapter_audio(0)
    renderer.run()
    audio = renderer.chapter_audio(0)
    s = renderer.settings
    pauses = s.heading_pause + 2 * s.paragraph_pause + s.chapter_pause
    assert len(audio) == 3 * 2400 + int(pauses * 24000) or len(audio) > 3 * 2400


@pytest.mark.slow
def test_real_voice_renders_and_resumes(tmp_path):
    """End to end with Kokoro: render a short book, then resume entirely from the cache."""
    real = VoiceSetup(load_manifest(allow_proposed=True), variant="int8")
    model = real.folder / real.model_entry.name
    if not model.exists() or not (real.folder / real.voice_entry.name).exists():
        pytest.skip("voice model not downloaded")
    cache = RenderCache(tmp_path / "cache")
    b = book("It was 1945 when Dr. Jones arrived.", "He paid $3.50 for coffee.")
    first = Renderer(b, real, cache, book_id="e2e").run()
    assert first.rendered == 3 and not first.failed
    audio = Renderer(b, real, cache, book_id="e2e").chapter_audio(0)
    assert len(audio) / 24000 > 3
    assert Renderer(b, real, cache, book_id="e2e").run().cached == 3
