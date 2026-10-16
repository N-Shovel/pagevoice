"""Pick the cleanup text rules for a book's language."""

from types import ModuleType


def rules_for(language: str) -> ModuleType:
    base = language.strip().lower().replace("_", "-").split("-")[0]
    if base == "en":
        from pagevoice.cleanup import en

        return en
    raise ValueError(f"PageVoice v1 reads English only; no cleanup rules for {language!r}")
