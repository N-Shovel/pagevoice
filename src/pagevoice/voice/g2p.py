"""Pick the G2P for a book's language. Each language has its own module (g2p_en, ...)."""

from collections.abc import Callable

G2P = Callable[[str], str]

# Provisional pick (docs/DECISIONS.md D29).
DEFAULT_BACKEND = "misaki"


def g2p_for(language: str, backend: str | None = None) -> G2P:
    base = language.lower().replace("_", "-").split("-")[0]
    if base == "en":
        from pagevoice.voice.g2p_en import EnglishG2P

        return EnglishG2P(backend or DEFAULT_BACKEND, british=language.lower() == "en-gb")
    raise ValueError(f"PageVoice v1 reads English only; no G2P for language {language!r}")
