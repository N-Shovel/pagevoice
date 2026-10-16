"""A book's language: normalise the code, refuse what v1 can't read, pick the text rules."""

from types import ModuleType

from pagevoice.document import IngestError

NOT_SUPPORTED = (
    "This book is marked as {name}. PageVoice reads English books only for now. If the "
    "book really is in English, open it again and choose English as its language."
)
_ALIASES = {"eng": "en", "english": "en"}


def normalize(code: str) -> str:
    """'en_GB' -> 'en-gb', 'eng' -> 'en', 'English' -> 'en'."""
    code = code.strip().lower().replace("_", "-")
    base, _, region = code.partition("-")
    base = _ALIASES.get(base, base)
    return f"{base}-{region}" if region else base


def base_of(code: str) -> str:
    return normalize(code).split("-")[0]


def book_language(found: str | None, override: str | None = None) -> str:
    """The language a book is read in: the caller's choice, else the file's, else English.

    Raises IngestError for a language PageVoice can't read yet (v1: English only).
    """
    chosen = normalize(override or found or "en") or "en"
    if base_of(chosen) != "en":
        raise IngestError(NOT_SUPPORTED.format(name=found or chosen))
    return chosen


def rules_for(language: str) -> ModuleType:
    if base_of(language) == "en":
        from pagevoice.cleanup import en

        return en
    raise IngestError(NOT_SUPPORTED.format(name=language))
