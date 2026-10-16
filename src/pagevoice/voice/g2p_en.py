"""English G2P (text to Kokoro phonemes). Language module: English rules live here only.

Two backends, compared in M0 (SPEC O1):
- "misaki": Kokoro's own G2P. Dictionary plus spaCy part-of-speech tags for heteronyms;
  words it doesn't know go to espeak-ng.
- "espeak": espeak-ng only, mapped to Kokoro's phoneme set by misaki.
"""

import logging
from functools import cache

log = logging.getLogger(__name__)

BACKENDS = ("misaki", "espeak")


class EnglishG2P:
    def __init__(self, backend: str = "misaki", *, british: bool = False) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"Unknown English G2P backend {backend!r}")
        self.backend = backend
        self.british = british
        self._g2p = _load(backend, british)

    def __call__(self, text: str) -> str:
        phonemes, _ = self._g2p(text)
        return phonemes or ""


@cache
def _load(backend: str, british: bool):
    from misaki import espeak

    language = "en-gb" if british else "en-us"
    if backend == "espeak":
        return espeak.EspeakG2P(language=language)

    from misaki import en

    fallback = espeak.EspeakFallback(british=british)
    # trf=False: the transformer tagger would pull in PyTorch (DECISIONS D3).
    return en.G2P(trf=False, british=british, fallback=fallback)
