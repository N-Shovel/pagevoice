"""Pick the G2P for a book's language. Each language has its own module (g2p_en, ...)."""

from collections.abc import Callable

G2P = Callable[[str], str]

# Provisional pick (docs/DECISIONS.md D29).
DEFAULT_BACKEND = "misaki"


def normalize_language(language: str) -> str:
    """'en_GB' -> 'en-gb'."""
    return language.strip().lower().replace("_", "-")


def g2p_for(language: str, backend: str | None = None) -> G2P:
    code = normalize_language(language)
    if code.split("-")[0] == "en":
        from pagevoice.voice.g2p_en import EnglishG2P

        return EnglishG2P(backend or DEFAULT_BACKEND, british=code == "en-gb")
    raise ValueError(f"PageVoice v1 reads English only; no G2P for language {language!r}")
