"""English G2P (text to Kokoro phonemes). Language module: English rules live here only.

Two backends, compared in M0 (SPEC O1):
- "misaki": Kokoro's own G2P. Dictionary plus spaCy part-of-speech tags for heteronyms;
  words it doesn't know go to espeak-ng.
- "espeak": espeak-ng only, mapped to Kokoro's phoneme set by misaki.
"""

import importlib.metadata
import importlib.util
import logging
from functools import cache

log = logging.getLogger(__name__)

BACKENDS = ("misaki", "espeak")
SPACY_MODEL = "en_core_web_sm"
UNKNOWN = "❓"  # misaki's marker for a word it couldn't pronounce


class G2PError(RuntimeError):
    """The G2P can't run (a bundled part is missing)."""


class EnglishG2P:
    def __init__(self, backend: str = "misaki", *, british: bool = False) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"Unknown English G2P backend {backend!r}")
        self.backend = backend
        self.british = british
        self._g2p = _load(backend, british)
        self.last_warning: str | None = None  # about the last call; for the render report

    def __call__(self, text: str) -> str:
        phonemes, _ = self._g2p(text)
        phonemes = phonemes or ""
        self.last_warning = None
        if text.strip() and not phonemes.strip():
            self.last_warning = "No speech could be made for this text; it will be silent."
        elif UNKNOWN in phonemes:
            self.last_warning = "Part of this text couldn't be pronounced; that part is silent."
        if self.last_warning:
            log.warning("%s %r", self.last_warning, text[:80])
        return phonemes.replace(UNKNOWN, "")


# Packages whose version changes the phonemes, so they belong in the render cache key.
_PACKAGES = {
    "misaki": ("misaki", "spacy", SPACY_MODEL, "espeakng-loader"),
    "espeak": ("misaki", "espeakng-loader", "phonemizer-fork"),
}


def version(backend: str) -> str:
    """'misaki=0.9.4 spacy=3.8.16 ...' for the cache key."""
    parts = []
    for package in _PACKAGES[backend]:
        try:
            parts.append(f"{package}={importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            parts.append(f"{package}=?")
    return " ".join(parts)


@cache
def _load(backend: str, british: bool):
    from misaki import espeak

    language = "en-gb" if british else "en-us"
    if backend == "espeak":
        return espeak.EspeakG2P(language=language)

    # misaki would pip-download the spaCy model if it's missing. PageVoice never goes
    # online for that (SPEC §2): the model ships with the app.
    if importlib.util.find_spec(SPACY_MODEL) is None:
        raise G2PError(
            f"The English language model ({SPACY_MODEL}) is missing from this install. "
            "Reinstall PageVoice."
        )
    import spacy.cli
    from misaki import en

    def refuse_download(*_args, **_kwargs):
        raise G2PError(
            f"The English language model ({SPACY_MODEL}) looks missing, and PageVoice "
            "doesn't download it. Reinstall PageVoice."
        )

    # misaki checks package metadata, which a frozen build may lack, and then calls
    # spacy.cli.download. Block that call while it builds.
    real_download = spacy.cli.download
    spacy.cli.download = refuse_download
    try:
        fallback = espeak.EspeakFallback(british=british)
        # trf=False: the transformer tagger would pull in PyTorch (DECISIONS D3).
        return en.G2P(trf=False, british=british, fallback=fallback)
    finally:
        spacy.cli.download = real_download
