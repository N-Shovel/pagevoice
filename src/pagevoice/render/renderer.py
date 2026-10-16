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

import numpy as np

from pagevoice.document import Book
from pagevoice.normalize import normalizer_for
from pagevoice.pronounce.lexicon import Entry, apply
from pagevoice.render.cache import KeyParts, RenderCache
from pagevoice.voice.engine import VoiceSetup
from pagevoice.voice.kokoro import SAMPLE_RATE

log = logging.getLogger(__name__)


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
        self.items = self.plan()

    def plan(self) -> list[Item]:
        normalize = normalizer_for(self.book.language)
        items = []
        for c, chapter in enumerate(self.book.chapters):
            paragraphs = [p for p in chapter.paragraphs if p.text]
            if not self.settings.drop_notes:
                paragraphs += [p for p in chapter.notes if p.text]
            for i, paragraph in enumerate(paragraphs):
                applied = apply(paragraph.text, self.pronunciations)
                spoken = applied.fill(normalize(applied.text))
                parts = KeyParts(
                    text=spoken,
                    entries=tuple(sorted(tuple(sorted(e.as_dict().items())) for e in applied.used)),
                    voice=self.voice.voice,
                    variant=self.voice.variant,
                    model_sha256=self.voice.model_entry.sha256,
                    voice_sha256=self.voice.voice_entry.sha256,
                    speed=self.settings.speed,
                    g2p=self.voice.g2p_name,
                    language=self.book.language,
                )
                items.append(
                    Item(c, i, paragraph.text, spoken, parts.key(), paragraph.kind == "heading")
                )
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
                audio = self.voice.synthesize(self.voice.phonemes(item.spoken), self.settings.speed)
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
