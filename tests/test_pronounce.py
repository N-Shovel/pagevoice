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
    assert applied.fill(applied.text) == "She will polish the poh-lish silver."


def test_whole_word_only():
    applied = apply("Anne and Annexe", [Entry("Anne", "Ann")])
    assert applied.fill(applied.text) == "ann and Annexe"
    loose = apply("Anne and Annexe", [Entry("Anne", "Ann", whole_word=False)])
    assert loose.fill(loose.text) == "ann and annxe"


def test_book_entries_override_global():
    merged = merge([Entry("Darcy", "DAR-see"), Entry("Leicester", "LESS-ter")],
                   [Entry("darcy", "DAR-sy")])  # fmt: skip
    applied = apply("Darcy went to Leicester.", merged)
    assert applied.fill(applied.text) == "dar-sy went to less-ter."
    assert {e.word for e in applied.used} == {"darcy", "Leicester"}


def test_book_entries_override_global_with_other_case_settings():
    merged = merge([Entry("Darcy", "DAR-see", case_sensitive=True)], [Entry("darcy", "DAR-sy")])
    applied = apply("Darcy and darcy.", merged)
    assert applied.fill(applied.text) == "dar-sy and dar-sy."
    # "Polish" is not "polish": the global entry still covers what the book entry doesn't.
    merged = merge([Entry("polish", "POL-ish")], [Entry("Polish", "POLE-ish", case_sensitive=True)])
    applied = apply("Polish polish.", merged)
    assert applied.fill(applied.text) == "pole-ish pol-ish."


def test_phonemes_use_misaki_markup_and_survive_normalization():
    applied = apply("NASA hired Kokoro.", [Entry("Kokoro", phonemes="kˈOkəɹO")])
    spoken = applied.fill(normalize(applied.text))
    assert spoken == "Nasa hired [Kokoro](/kˈOkəɹO/)."


def test_longer_entries_win():
    merged = merge([Entry("York", "YORK")], [Entry("New York", "noo-YORK")])
    applied = apply("New York and York", merged)
    assert applied.fill(applied.text) == "noo-york and york"


@pytest.mark.parametrize(
    "line", ["\tfoo\n", "Anne\n", "Anne\tAnn\t\tmaybe\n"], ids=["no word", "no sound", "bad flag"]
)
def test_bad_rows_are_explained(line):
    with pytest.raises(LexiconError, match="Line 1"):
        parse(line)


def test_possessives_and_quotes_still_match_whole_words():
    entries = [Entry("Hermione", "her-MY-oh-nee"), Entry("Brien", "BRY-en")]
    for text, spoken in [
        ("Hermione's wand.", "her-my-oh-nee's wand."),
        ("Hermione’s wand.", "her-my-oh-nee’s wand."),
        ("'Hermione,' he said.", "'her-my-oh-nee,' he said."),
        ("O'Brien left.", "O'Brien left."),
        ("Hermione'll come.", "her-my-oh-nee'll come."),
    ]:
        applied = apply(text, entries)
        assert applied.fill(applied.text) == spoken


def test_names_in_the_list_keep_their_context_for_the_normalizer():
    entries = [Entry("Jones", "JOHNZ"), Entry("Henry", "HEN-ree")]
    applied = apply("Dr. Jones met Henry VIII.", entries)
    assert applied.fill(normalize(applied.text)) == "Doctor johnz met hen-ree the Eighth."


def test_many_entries_get_distinct_placeholders():
    entries = [Entry(f"Name{n}", f"spoken{n}") for n in range(25)]
    text = " ".join(f"Name{n}" for n in range(25))
    applied = apply(text, entries)
    assert applied.fill(applied.text) == " ".join(f"spoken{n}" for n in range(25))


@pytest.mark.slow
def test_respellings_and_phonemes_reach_misaki_intact():
    """Through the real G2P: a capitalised respelling isn't spelled out as letters, and
    phoneme markup comes out exactly as written."""
    import importlib.util

    from pagevoice.voice.g2p import g2p_for

    if importlib.util.find_spec("en_core_web_sm") is None:
        pytest.skip("spaCy English model not installed")
    g2p = g2p_for("en")

    def spoken(text, entries):
        applied = apply(text, entries)
        return g2p(applied.fill(normalize(applied.text)))

    assert spoken("Darcy smiled.", [Entry("Darcy", "DAR-see")]) == g2p("dar-see smiled.")
    assert "dˌi" not in spoken("Darcy smiled.", [Entry("Darcy", "DAR-see")])  # not "D A R"
    assert "kˈOkəɹO" in spoken("Kokoro spoke.", [Entry("Kokoro", phonemes="kˈOkəɹO")])
    assert g2p.last_warning is None


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16", "utf-8-sig", "utf-8"])
def test_lists_saved_by_excel_are_read(tmp_path, encoding):
    """Excel's "Text (Tab delimited)" is Windows-1252 and "Unicode Text" is UTF-16."""
    path = tmp_path / "names.tsv"
    path.write_bytes("Siobhán\tshi-vawn\r\nNiamh\tneev\r\n".encode(encoding))
    assert [(e.word, e.sounds_like) for e in load(path)] == [
        ("Siobhán", "shi-vawn"), ("Niamh", "neev")
    ]  # fmt: skip
