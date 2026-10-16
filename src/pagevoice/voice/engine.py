"""The voice as the renderer sees it: verified model files, G2P and Kokoro, loaded lazily."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pagevoice.voice.download import Progress, ensure_file, is_valid, models_dir
from pagevoice.voice.manifest import Manifest

DEFAULT_VOICE = "af_heart"  # provisional (D31)
DEFAULT_VARIANT = "fp32"  # provisional (D30)


class VoiceNotReady(RuntimeError):
    """The model files haven't been downloaded yet (first run)."""


@dataclass
class VoiceSetup:
    manifest: Manifest
    variant: str = DEFAULT_VARIANT
    voice: str = DEFAULT_VOICE
    language: str = "en"
    g2p_backend: str | None = None
    provider: str = "cpu"
    folder: Path = field(default_factory=models_dir)
    _kokoro: object = None
    _g2p: Callable[[str], str] | None = None
    _verified: bool = False  # ready() passed once; later checks only look at the sizes
    # One voice can serve a render and a preview at once: G2P and synthesis take turns.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @property
    def model_entry(self):
        return self.manifest.model_entry(self.variant)

    @property
    def voice_entry(self):
        return self.manifest.voice_entry(self.voice)

    def ready(self) -> bool:
        """True if both files are present and pass their checksums. That hashes ~300 MB the
        first time; after it has passed once, only the sizes are checked."""
        entries = (self.model_entry, self.voice_entry)
        if self._verified:
            paths = [(self.folder / e.name, e) for e in entries]
            return all(p.is_file() and p.stat().st_size == e.size for p, e in paths)
        self._verified = all(is_valid(self.folder / e.name, e) for e in entries)
        return self._verified

    def download(self, progress: Progress | None = None, *, use_source: bool = False) -> None:
        """The first-run download: the only network access in PageVoice."""
        for entry in (self.model_entry, self.voice_entry):
            ensure_file(entry, self.folder, use_source=use_source, progress=progress)

    def _paths(self) -> tuple[Path, Path]:
        model = self.folder / self.model_entry.name
        voice = self.folder / self.voice_entry.name
        for path, entry in ((model, self.model_entry), (voice, self.voice_entry)):
            # Size only: hashing the model on every call would take seconds. ready() and
            # download() do the full checksum.
            if not path.is_file() or path.stat().st_size != entry.size:
                raise VoiceNotReady("The voice hasn't been downloaded yet, or is incomplete.")
        return model, voice

    def use_language(self, language: str) -> None:
        """Read in this language from now on (a book's language, e.g. 'en-GB')."""
        with self._lock:
            if language != self.language:
                self.language = language
                self._g2p = None

    def phonemes(self, text: str) -> str:
        with self._lock:
            if self._g2p is None:
                from pagevoice.voice.g2p import g2p_for

                self._g2p = g2p_for(self.language, self.g2p_backend)
            return self._g2p(text)

    def synthesize(self, phonemes: str, speed: float = 1.0) -> np.ndarray:
        model_path, voice_path = self._paths()
        with self._lock:
            if self._kokoro is None:
                from pagevoice.voice.kokoro import Kokoro

                self._kokoro = Kokoro(model_path, provider=self.provider)
            return self._kokoro.synthesize(phonemes, voice_path, speed)

    @property
    def g2p_warning(self) -> str | None:
        """What the G2P couldn't pronounce in the last phonemes() call, in plain words."""
        return getattr(self._g2p, "last_warning", None)

    @property
    def g2p_name(self) -> str:
        """The G2P backend and its package versions, for the render cache key."""
        from pagevoice.voice.g2p import g2p_version

        return g2p_version(self.language, self.g2p_backend)
