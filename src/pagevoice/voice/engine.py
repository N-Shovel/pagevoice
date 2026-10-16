"""The voice as the renderer sees it: verified model files, G2P and Kokoro, loaded lazily."""

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

    @property
    def model_entry(self):
        return self.manifest.model_entry(self.variant)

    @property
    def voice_entry(self):
        return self.manifest.voice_entry(self.voice)

    def ready(self) -> bool:
        """True if both files are present and pass their checksums (hashes ~300 MB)."""
        return all(is_valid(self.folder / e.name, e) for e in (self.model_entry, self.voice_entry))

    def download(self, progress: Progress | None = None, *, use_source: bool = False) -> None:
        """The first-run download: the only network access in PageVoice."""
        for entry in (self.model_entry, self.voice_entry):
            ensure_file(entry, self.folder, use_source=use_source, progress=progress)

    def _paths(self) -> tuple[Path, Path]:
        model = self.folder / self.model_entry.name
        voice = self.folder / self.voice_entry.name
        if not (model.is_file() and voice.is_file()):
            raise VoiceNotReady("The voice hasn't been downloaded yet.")
        return model, voice

    def phonemes(self, text: str) -> str:
        if self._g2p is None:
            from pagevoice.voice.g2p import g2p_for

            self._g2p = g2p_for(self.language, self.g2p_backend)
        return self._g2p(text)

    def synthesize(self, phonemes: str, speed: float = 1.0) -> np.ndarray:
        model_path, voice_path = self._paths()
        if self._kokoro is None:
            from pagevoice.voice.kokoro import Kokoro

            self._kokoro = Kokoro(model_path, provider=self.provider)
        return self._kokoro.synthesize(phonemes, voice_path, speed)

    @property
    def g2p_name(self) -> str:
        from pagevoice.voice.g2p import DEFAULT_BACKEND

        return self.g2p_backend or DEFAULT_BACKEND
