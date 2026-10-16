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
