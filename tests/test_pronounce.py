"""Pronunciation lists: TSV with or without BOM, whole-word and case options, overrides."""

import pytest

from pagevoice.normalize.en import normalize
from pagevoice.pronounce.lexicon import Entry, LexiconError, apply, dump, load, merge, parse


def test_tsv_with_bom_and_header(tmp_path):
    path = tmp_path / "names.tsv"
    path.write_bytes(
        "﻿word\tsounds_like\tphonemes\twhole_word\tcase_sensitive\tnote\n"
        "Hermione\ther-MY-oh-nee\t\t\t\tthe witch\n"
        "Polish\tPOH-lish\t\tyes\tyes\t\n".encode()
    )
    entries = load(path)
    assert [e.word for e in entries] == ["Hermione", "Polish"]
    assert entries[1].case_sensitive and not entries[0].case_sensitive
    assert parse(dump(entries)) == entries  # round trip


def test_case_sensitive_keeps_polish_and_polish_apart():
    entries = [Entry("Polish", "POH-lish", case_sensitive=True)]
    applied = apply("She will polish the Polish silver.", entries)
    assert applied.fill(applied.text) == "She will polish the POH-lish silver."


def test_whole_word_only():
    applied = apply("Anne and Annexe", [Entry("Anne", "Ann")])
    assert applied.fill(applied.text) == "Ann and Annexe"
    loose = apply("Anne and Annexe", [Entry("Anne", "Ann", whole_word=False)])
    assert loose.fill(loose.text) == "Ann and Annxe"


def test_book_entries_override_global():
    merged = merge([Entry("Darcy", "DAR-see"), Entry("Leicester", "LESS-ter")],
                   [Entry("darcy", "DAR-sy")])  # fmt: skip
    applied = apply("Darcy went to Leicester.", merged)
    assert applied.fill(applied.text) == "DAR-sy went to LESS-ter."
    assert {e.word for e in applied.used} == {"darcy", "Leicester"}


def test_phonemes_use_misaki_markup_and_survive_normalization():
    applied = apply("NASA hired Kokoro.", [Entry("Kokoro", phonemes="kˈOkəɹO")])
    spoken = applied.fill(normalize(applied.text))
    assert spoken == "Nasa hired [Kokoro](/kˈOkəɹO/)."


def test_longer_entries_win():
    merged = merge([Entry("York", "YORK")], [Entry("New York", "noo-YORK")])
    applied = apply("New York and York", merged)
    assert applied.fill(applied.text) == "noo-YORK and YORK"


@pytest.mark.parametrize(
    "line", ["\tfoo\n", "Anne\n", "Anne\tAnn\t\tmaybe\n"], ids=["no word", "no sound", "bad flag"]
)
def test_bad_rows_are_explained(line):
    with pytest.raises(LexiconError, match="Line 1"):
        parse(line)
