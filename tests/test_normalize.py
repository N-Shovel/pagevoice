"""English normalizer against the fixed sentence list (tests/voice/sentences.tsv).

The expected spoken forms come from that human-owned file, never from this test. Words are
compared without case or punctuation: "a.m." and "a m" are said the same way.
"""

import re

import pytest

from pagevoice.normalize.en import cardinal, normalize, ordinal, roman_value, year
from tests.test_sentence_list import read_rows


def words(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("-", " ")
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)


ROWS = [
    pytest.param(row[2], row[3] if len(row) > 3 and row[3].strip() else row[2], id=row[0])
    for row in read_rows()
]


@pytest.mark.parametrize(("text", "spoken"), ROWS)
def test_sentence_list(text, spoken):
    assert words(normalize(text)) == words(spoken)


def test_numbers():
    assert cardinal(12408) == "twelve thousand four hundred eight"
    assert cardinal(1_000_000) == "one million"
    assert ordinal(22) == "twenty-second" and ordinal(103) == "one hundred third"
    assert year(1905) == "nineteen oh five" and year(2008) == "two thousand eight"
    assert year(1900) == "nineteen hundred"


def test_roman_numerals_need_to_be_canonical():
    assert roman_value("XIV") == 14
    assert roman_value("IIII") is None
    assert roman_value("MIX") == 1009


def test_ordinary_prose_is_left_alone():
    text = "I said that a man in possession of a good fortune must be in want of a wife."
    assert normalize(text) == text


def test_all_caps_words_are_read_as_words():
    assert normalize("IT is a truth") == "It is a truth"
    assert normalize("BOOK II. CHAPTER I.") == "Book two. Chapter one."


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("The army had 1500 soldiers.", "The army had one thousand five hundred soldiers."),
        ("1914 changed everything.", "nineteen fourteen changed everything."),
        ("It was 1945.", "It was nineteen forty-five."),
        (
            "between 1914 and 1918 the war",
            "between nineteen fourteen and nineteen eighteen the war",
        ),
        ("in AD 1215 they signed", "in A D twelve fifteen they signed"),
        ("summer of 1969 was hot", "summer of nineteen sixty-nine was hot"),
    ],
)
def test_four_digit_numbers_are_years_only_with_context(text, spoken):
    assert words(normalize(text)) == words(spoken)


def test_slash_dates_are_not_fractions():
    assert words(normalize("Born 12/25/1990.")) == words("Born twelve twenty-five nineteen ninety.")
    assert words(normalize("Add 3/4 cup.")) == words("Add three quarters cup.")


def test_lone_i_after_a_lowercase_keyword_is_the_pronoun():
    assert normalize("He read the letter I sent.") == "He read the letter I sent."
    assert normalize("See volume I.") == "See volume one."
    assert normalize("Chapter I begins.") == "Chapter one begins."


def test_us_is_spelled_out_except_in_capitals():
    assert normalize("She moved to the US in May.") == "She moved to the U S in May."
    assert normalize("LET US GO HOME") == "Let Us Go Home"
