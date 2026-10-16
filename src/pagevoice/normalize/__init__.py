"""Text normalization: turn printed text into what a reader says. One module per language."""

from collections.abc import Callable


def normalizer_for(language: str) -> Callable[[str], str]:
    base = language.strip().lower().replace("_", "-").split("-")[0]
    if base in ("en", "eng", "english"):
        from pagevoice.normalize.en import normalize

        return normalize
    raise ValueError(f"PageVoice v1 reads English only; no normalizer for {language!r}")
