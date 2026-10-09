"""The fixed voice sentence list must stay well-formed; benchmarks and round-trips read it."""

from pathlib import Path

SENTENCES = Path(__file__).resolve().parent / "voice" / "sentences.tsv"
CATEGORIES = {
    "numbers",
    "dates",
    "money",
    "abbreviations",
    "roman_numerals",
    "dialogue",
    "long_sentences",
    "names",
    "heteronyms",
    "symbols",
}


def read_rows() -> list[list[str]]:
    lines = SENTENCES.read_text(encoding="utf-8").splitlines()
    rows = [line.split("\t") for line in lines if line and not line.startswith("#")]
    assert rows[0][:3] == ["id", "category", "text"], "missing header row"
    return rows[1:]


def test_rows_are_well_formed():
    for row in read_rows():
        assert len(row) in (3, 4), f"expected 3 or 4 tab-separated columns: {row}"
        assert row[1] in CATEGORIES, f"unknown category {row[1]!r} in {row[0]}"
        assert row[2].strip(), f"empty text in {row[0]}"


def test_ids_are_unique():
    ids = [row[0] for row in read_rows()]
    assert len(ids) == len(set(ids))


def test_every_category_is_covered():
    assert {row[1] for row in read_rows()} == CATEGORIES
