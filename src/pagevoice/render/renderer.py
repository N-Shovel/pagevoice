"""Render a book paragraph by paragraph into the cache, with progress, pause, cancel and
resume (SPEC §8, D16).

For each readable paragraph: pronunciation entries are swapped in, the text is normalized
for the book's language, and the cache key is computed from everything that changes the
audio. Paragraphs already in the cache are skipped, which is what makes resuming after a
crash, or re-rendering one edited paragraph, cheap.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile

from pagevoice.document import Book
from pagevoice.normalize import normalizer_for
from pagevoice.pronounce.lexicon import Entry, apply
from pagevoice.render.cache import KeyParts, RenderCache
from pagevoice.voice.engine import VoiceSetup
from pagevoice.voice.kokoro import SAMPLE_RATE

log = logging.getLogger(__name__)


def spoken_text(text: str, entries: list[Entry], normalize) -> tuple[str, list[Entry]]:
    """What the G2P gets for text: pronunciation entries swapped in, then normalized
    (D33). Returns the text and the entries that matched."""
    applied = apply(text, entries)
    return applied.fill(normalize(applied.text)), applied.used


def speak(
    text: str,
    voice: VoiceSetup,
    *,
    language: str = "en",
    pronunciations: list[Entry] | None = None,
    speed: float = 1.0,
) -> np.ndarray:
    """Say a short text exactly as a book would: for previews (SPEC §5)."""
    voice.use_language(language)
    spoken, _ = spoken_text(text, pronunciations or [], normalizer_for(language))
    return voice.synthesize(voice.phonemes(spoken), speed)


@dataclass(frozen=True)
class RenderSettings:
    speed: float = 1.0  # provisional default (D31)
    drop_notes: bool = False  # D11: notes are read at the chapter's end unless dropped
    paragraph_pause: float = 0.45  # seconds of silence between paragraphs
    heading_pause: float = 1.0  # after a heading
    chapter_pause: float = 1.5  # at the end of a chapter


@dataclass(frozen=True)
class Item:
    chapter: int
    paragraph: int  # index in the chapter's readable list
    source: str  # the paragraph as the book has it
    spoken: str  # what goes to the G2P: normalized, pronunciation applied
    key: str
    heading: bool
    position: int = 0  # where it sits in the chapter: paragraph index, notes after the body


@dataclass(frozen=True)
class Segment:
    """One paragraph's place in a chapter's audio, for playback (no audio loaded)."""

    item: Item
    frames: int | None  # None: not rendered yet
    pause: int  # frames of silence after it


@dataclass
class Progress:
    done: int
    total: int
    rendered: int  # done in this run (the rest came from the cache)
    audio_seconds: float
    elapsed: float
    eta_seconds: float | None  # from the speed measured in this run
    current: Item | None = None


@dataclass
class Result:
    rendered: int = 0
    cached: int = 0
    cancelled: bool = False
    failed: list[tuple[Item, str]] = field(default_factory=list)
    warnings: list[tuple[Item, str]] = field(default_factory=list)  # text the G2P dropped


def _key_entry(entry: Entry) -> tuple:
    """An entry as it affects the audio: its note doesn't."""
    return tuple(sorted((k, v) for k, v in entry.as_dict().items() if k != "note"))


class Renderer:
    def __init__(
        self,
        book: Book,
        voice: VoiceSetup,
        cache: RenderCache,
        *,
        book_id: str,
        settings: RenderSettings | None = None,
        pronunciations: list[Entry] | None = None,
    ) -> None:
        self.book = book
        self.voice = voice
        self.cache = cache
        self.book_id = book_id
        self.settings = settings or RenderSettings()
        self.pronunciations = pronunciations or []
        voice.use_language(book.language)  # e.g. British spelling and phonemes for en-GB
        self.items = self.plan()

    def plan(self) -> list[Item]:
        normalize = normalizer_for(self.book.language)
        g2p = self.voice.g2p_name  # reads package metadata: once, not per paragraph
        items = []
        for c, chapter in enumerate(self.book.chapters):
            body = len(chapter.paragraphs)
            paragraphs = [(n, p) for n, p in enumerate(chapter.paragraphs) if p.text]
            if not self.settings.drop_notes:
                paragraphs += [(body + n, p) for n, p in enumerate(chapter.notes) if p.text]
            for i, (position, paragraph) in enumerate(paragraphs):
                spoken, used = spoken_text(paragraph.text, self.pronunciations, normalize)
                parts = KeyParts(
                    text=spoken,
                    entries=tuple(sorted(_key_entry(e) for e in used)),
                    voice=self.voice.voice,
                    variant=self.voice.variant,
                    model_sha256=self.voice.model_entry.sha256,
                    voice_sha256=self.voice.voice_entry.sha256,
                    speed=self.settings.speed,
                    g2p=g2p,
                    language=self.book.language,
                )
                heading = paragraph.kind == "heading"
                items.append(Item(c, i, paragraph.text, spoken, parts.key(), heading, position))
        self.cache.remember(self.book_id, [item.key for item in items])
        return items

    def pending(self) -> list[Item]:
        return [item for item in self.items if not self.cache.has(item.key)]

    def run(
        self,
        on_progress: Callable[[Progress], None] | None = None,
        *,
        stop: threading.Event | None = None,
        pause: threading.Event | None = None,
    ) -> Result:
        """Render every paragraph not yet cached. Safe to call again after a stop or crash."""
        stop = stop or threading.Event()
        pause = pause or threading.Event()
        result = Result(cached=len(self.items) - len(self.pending()))
        todo = self.pending()
        started = time.perf_counter()
        audio_seconds = 0.0
        busy = 0.0  # time spent rendering, not paused
        remaining_chars = sum(len(i.spoken) for i in todo)
        chars_done = 0
        for item in todo:
            while pause.is_set() and not stop.is_set():
                stop.wait(0.2)
            if stop.is_set():
                result.cancelled = True
                break
            t0 = time.perf_counter()
            try:
                phonemes = self.voice.phonemes(item.spoken)
                if warning := self.voice.g2p_warning:
                    result.warnings.append((item, warning))
                audio = self.voice.synthesize(phonemes, self.settings.speed)
            except Exception as exc:  # one bad paragraph mustn't stop the book
                log.exception(
                    "Rendering failed for chapter %d paragraph %d", item.chapter, item.paragraph
                )
                result.failed.append((item, str(exc)))
                continue
            self.cache.put(item.key, audio, SAMPLE_RATE)
            busy += time.perf_counter() - t0
            audio_seconds += len(audio) / SAMPLE_RATE
            chars_done += len(item.spoken)
            result.rendered += 1
            if on_progress:
                rate = chars_done / busy if busy else 0
                eta = (remaining_chars - chars_done) / rate if rate else None
                on_progress(
                    Progress(
                        done=result.cached + result.rendered,
                        total=len(self.items),
                        rendered=result.rendered,
                        audio_seconds=audio_seconds,
                        elapsed=time.perf_counter() - started,
                        eta_seconds=eta,
                        current=item,
                    )
                )
        self.cache.trim(protect={item.key for item in self.items})
        return result

    def _pause(self, item: Item) -> int:
        seconds = self.settings.heading_pause if item.heading else self.settings.paragraph_pause
        return int(seconds * SAMPLE_RATE)

    def timeline(self, chapter: int) -> list[Segment]:
        """The chapter as playback sees it: each paragraph's length (read from the cache
        file's header, no audio loaded) and the pause after it, in reading order."""
        return [
            Segment(item, self.cache.frames(item.key), self._pause(item))
            for item in self.items
            if item.chapter == chapter
        ]

    def first_at(self, chapter: int, position: int) -> int:
        """Index in timeline(chapter) of the first paragraph at or after a paragraph of
        the book (e.g. one right-clicked in review); 0 if there's none."""
        segments = [i for i in self.items if i.chapter == chapter]
        return next((n for n, item in enumerate(segments) if item.position >= position), 0)

    def write_chapter(self, chapter: int, path: Path, *, format: str = "FLAC") -> float:
        """Write a chapter's audio, with pauses, to a file one paragraph at a time, so a
        ten-hour single-chapter book needs no more memory than one paragraph. Returns its
        length in seconds. Every paragraph must be rendered (LookupError otherwise)."""
        items = [i for i in self.items if i.chapter == chapter]
        if any(not self.cache.has(i.key) for i in items):
            raise LookupError(f"Chapter {chapter + 1} isn't fully rendered yet.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = 0
        with soundfile.SoundFile(
            str(path), "w", SAMPLE_RATE, 1, subtype="PCM_16", format=format
        ) as out:
            for item in items:
                audio = self.cache.get(item.key)
                if audio is None:  # removed since the check (unreadable or evicted)
                    raise LookupError(f"Chapter {chapter + 1} isn't fully rendered yet.")
                for block in (np.clip(audio, -1.0, 1.0), np.zeros(self._pause(item), np.float32)):
                    out.write(block)
                    frames += len(block)
            tail = np.zeros(int(self.settings.chapter_pause * SAMPLE_RATE), dtype=np.float32)
            out.write(tail)
            frames += len(tail)
        return frames / SAMPLE_RATE

    def chapter_audio(self, chapter: int) -> np.ndarray:
        """A chapter's audio from the cache, with pauses. Every paragraph must be rendered."""
        pieces = []
        for item in (i for i in self.items if i.chapter == chapter):
            audio = self.cache.get(item.key)
            if audio is None:
                raise LookupError(f"Chapter {chapter + 1} isn't fully rendered yet.")
            pause = self.settings.heading_pause if item.heading else self.settings.paragraph_pause
            pieces += [audio, np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32)]
        pieces.append(np.zeros(int(self.settings.chapter_pause * SAMPLE_RATE), dtype=np.float32))
        return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
