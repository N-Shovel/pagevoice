"""Pronunciation lists (SPEC §5, D15).

A list is a TSV file people can edit in a spreadsheet:

    word<TAB>sounds_like<TAB>phonemes<TAB>whole_word<TAB>case_sensitive<TAB>note

Only `word` and one of `sounds_like` / `phonemes` are needed; the flag columns take
yes/no (default: whole word yes, case-sensitive no). A header row is optional, and files
with or without a UTF-8 byte-order mark (Excel adds one) are accepted.

Per-book entries override global ones for the same word. Entries are applied to the text
before G2P, and the entries that matched are part of a paragraph's cache key.
"""

import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

COLUMNS = ["word", "sounds_like", "phonemes", "whole_word", "case_sensitive", "note"]
_YES = {"yes", "y", "true", "1", "x"}
_NO = {"no", "n", "false", "0", ""}


class LexiconError(ValueError):
    """A pronunciation file PageVoice can't use. The message is plain language."""


@dataclass(frozen=True)
class Entry:
    word: str
    sounds_like: str = ""
    phonemes: str = ""  # Kokoro/misaki phonemes; wins over sounds_like when both are set
    whole_word: bool = True
    case_sensitive: bool = False
    note: str = ""

    def key(self) -> tuple[str, bool]:
        return (self.word if self.case_sensitive else self.word.lower(), self.case_sensitive)

    def pattern(self) -> re.Pattern:
        body = re.escape(self.word)
        if self.whole_word:
            # Not inside a word. "Hermione's", "Hermione'll" and a quoted 'Hermione' still
            # match; "Brien" doesn't match inside "O'Brien".
            body = rf"(?<!\w)(?<!\w['’]){body}(?!\w)"
        return re.compile(body, 0 if self.case_sensitive else re.IGNORECASE)

    def replacement(self) -> str:
        if self.phonemes:
            # misaki's inline override: [word](/phonemes/)
            return f"[{self.word}](/{self.phonemes.strip('/')}/)"
        return self.sounds_like

    def as_dict(self) -> dict:
        return asdict(self)


def _flag(value: str, default: bool, line: int, column: str) -> bool:
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in _YES:
        return True
    if value in _NO:
        return False
    raise LexiconError(f"Line {line}: '{column}' should be yes or no, not '{value}'.")


def parse(text: str) -> list[Entry]:
    text = text.lstrip("﻿")
    entries = []
    rows = csv.reader(io.StringIO(text), delimiter="\t")
    for line, row in enumerate(rows, 1):
        if not row or not any(cell.strip() for cell in row) or row[0].startswith("#"):
            continue
        if line == 1 and row[0].strip().lower() == "word":
            continue  # header
        row = [cell.strip() for cell in row] + [""] * (len(COLUMNS) - len(row))
        word, sounds_like, phonemes = row[0], row[1], row[2]
        if not word:
            raise LexiconError(f"Line {line}: the word is empty.")
        if not sounds_like and not phonemes:
            raise LexiconError(f"Line {line}: '{word}' needs a 'sounds like' or phonemes.")
        entries.append(
            Entry(
                word=word,
                sounds_like=sounds_like,
                phonemes=phonemes,
                whole_word=_flag(row[3], True, line, "whole_word"),
                case_sensitive=_flag(row[4], False, line, "case_sensitive"),
                note=row[5],
            )
        )
    return entries


def load(path: Path) -> list[Entry]:
    try:
        return parse(Path(path).read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise LexiconError("This pronunciation list isn't UTF-8 text. Save it as UTF-8.") from exc


def dump(entries: list[Entry]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS)
    for e in entries:
        flags = ["yes" if e.whole_word else "no", "yes" if e.case_sensitive else "no"]
        writer.writerow([e.word, e.sounds_like, e.phonemes, *flags, e.note])
    return out.getvalue()


def save(path: Path, entries: list[Entry]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dump(entries), encoding="utf-8")
    tmp.replace(path)


def merge(global_entries: list[Entry], book_entries: list[Entry]) -> list[Entry]:
    """Per-book entries replace global ones for the same word (and case setting).

    Where their case settings differ, both stay, and the book entry wins wherever it
    matches: it is applied first, and its placeholder stops the global one matching there.
    """
    book_keys = {e.key() for e in book_entries}
    kept = [e for e in global_entries if e.key() not in book_keys]
    # Longer words first, so "New York" wins over "York". The sort is stable, so on equal
    # length a book entry still comes before a global one.
    return sorted(list(book_entries) + kept, key=lambda e: -len(e.word))


# A placeholder looks like an ordinary word, capitalised like the word it replaces, so the
# normalizer still sees a name after "Dr." or before "VIII". The letters can't form a
# Roman numeral, an abbreviation or an all-capital word: "Qzxv" + index as a-j + "q".
_PLACEHOLDER = re.compile(r"[Qq]zxv([a-j]+)q")


def _placeholder(index: int, capital: bool) -> str:
    digits = "".join(chr(ord("a") + int(d)) for d in str(index))
    return f"{'Q' if capital else 'q'}zxv{digits}q"


@dataclass
class Applied:
    """Text with each matched word swapped for a placeholder, ready for normalization.

    fill() puts the respellings or phoneme markup back afterwards.
    """

    text: str
    used: list[Entry]
    replacements: list[str]

    def fill(self, text: str) -> str:
        def back(match: re.Match) -> str:
            index = int("".join(str(ord(c) - ord("a")) for c in match.group(1)))
            return self.replacements[index]

        return _PLACEHOLDER.sub(back, text)


def apply(text: str, entries: list[Entry]) -> Applied:
    """Swap each entry's word for a placeholder; remember which entries matched."""
    used: list[Entry] = []
    replacements: list[str] = []
    for entry in entries:
        found = False

        def swap(match, entry=entry):
            nonlocal found
            if match.group("kept"):
                return match.group(0)
            found = True
            replacements.append(entry.replacement())
            return _placeholder(len(replacements) - 1, match.group(0)[:1].isupper())

        # Earlier placeholders match first and are kept as they are, so a shorter entry
        # can't match inside a longer one's ("York" inside "New York").
        pattern = entry.pattern()
        either = re.compile(rf"(?P<kept>[Qq]zxv[a-j]+q)|{pattern.pattern}", pattern.flags)
        text = either.sub(swap, text)
        if found:
            used.append(entry)
    return Applied(text, used, replacements)
