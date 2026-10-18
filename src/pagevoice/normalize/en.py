"""English text normalization (en-US reading): numbers, dates, money, abbreviations,
Roman numerals and symbols become words, so the G2P never has to guess.

The expected spoken forms are in tests/voice/sentences.tsv (human-owned); the tests read
that file. Rules here are deliberately narrow: when a pattern is ambiguous, the text is
left as printed and the G2P reads it.
"""

import re

# --- numbers ------------------------------------------------------------------------

ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")]
ORDINAL_WORDS = {
    "one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
    "nine": "ninth", "twelve": "twelfth",
}  # fmt: skip
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def cardinal(n: int) -> str:
    """American style, no "and": 12408 -> twelve thousand four hundred eight."""
    if n < 0:
        return "minus " + cardinal(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return TENS[tens] + (f"-{ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{ONES[hundreds]} hundred" + (f" {cardinal(rest)}" if rest else "")
    for value, name in SCALES:
        if n >= value:
            high, rest = divmod(n, value)
            return f"{cardinal(high)} {name}" + (f" {cardinal(rest)}" if rest else "")
    raise AssertionError(n)


def ordinal(n: int) -> str:
    words = cardinal(n)
    head, sep, last = words.rpartition(" ") if " " in words else ("", "", words)
    hyphen_head, dash, last_part = last.rpartition("-")
    target = last_part if dash else last
    if target in ORDINAL_WORDS:
        target = ORDINAL_WORDS[target]
    elif target.endswith("y"):
        target = target[:-1] + "ieth"
    else:
        target += "th"
    last = f"{hyphen_head}-{target}" if dash else target
    return f"{head}{sep}{last}"


def year(n: int) -> str:
    """1945 -> nineteen forty-five, 1905 -> nineteen oh five, 1066 -> ten sixty-six,
    2008 -> two thousand eight, 1000 -> one thousand."""
    if n % 1000 < 10:
        return cardinal(n)
    high, low = divmod(n, 100)
    if low == 0:
        return f"{cardinal(high)} hundred"
    if low < 10:
        return f"{cardinal(high)} oh {cardinal(low)}"
    return f"{cardinal(high)} {cardinal(low)}"


def plural(words: str) -> str:
    """forty -> forties, nineties; six -> sixes."""
    if words.endswith("y"):
        return words[:-1] + "ies"
    if words.endswith(("x", "s")):
        return words + "es"
    return words + "s"


def decimal(text: str) -> str:
    whole, _, frac = text.partition(".")
    out = cardinal(int(whole.replace(",", "") or 0))
    if frac:
        out += " point " + " ".join(ONES[int(d)] for d in frac)
    return out


def is_year(n: int) -> bool:
    return 1100 <= n <= 2099


# --- abbreviations ------------------------------------------------------------------

TITLES = {
    "Mr.": "Mister", "Mrs.": "Missus", "Ms.": "Miz", "Dr.": "Doctor", "Prof.": "Professor",
    "Gen.": "General", "Col.": "Colonel", "Lt.": "Lieutenant", "Capt.": "Captain",
    "Sgt.": "Sergeant", "Rev.": "Reverend", "Hon.": "Honorable", "Gov.": "Governor",
    "Sen.": "Senator", "Rep.": "Representative", "Pres.": "President", "St.": "Saint",
    "Mt.": "Mount", "Ft.": "Fort", "Maj.": "Major", "Cmdr.": "Commander", "Adm.": "Admiral",
}  # fmt: skip
AFTER_NAME = {"Dr.": "Drive", "St.": "Street", "Ave.": "Avenue", "Rd.": "Road", "Jr.": "Junior",
              "Sr.": "Senior", "Bros.": "Brothers", "Co.": "Company", "Ltd.": "Limited",
              "Inc.": "Incorporated", "Blvd.": "Boulevard", "Ln.": "Lane"}  # fmt: skip
PHRASES = {
    "e.g.": "for example", "i.e.": "that is", "etc.": "et cetera", "vs.": "versus",
    "viz.": "namely", "cf.": "compare", "approx.": "approximately", "a.m.": "a m",
    "p.m.": "p m", "A.M.": "a m", "P.M.": "p m", "A.D.": "A D", "B.C.": "B C",
}  # fmt: skip
# Abbreviations that often end a sentence ("…at 5 p.m. The bell rang."); "e.g." and "vs."
# are followed by names mid-sentence, so they never keep a full stop.
SENTENCE_FINAL = {"etc.", "a.m.", "p.m.", "A.M.", "P.M.", "A.D.", "B.C."}
# Capitalised words that start sentences far more often than they're names.
SENTENCE_STARTERS = {
    "The", "A", "An", "He", "She", "It", "They", "We", "I", "You", "But", "And", "Then",
    "There", "This", "That", "These", "Those", "His", "Her", "Its", "Their", "Our", "In",
    "On", "At", "When", "After", "Before", "As", "If", "So", "Yet", "Now", "No",
}  # fmt: skip
BEFORE_NUMBER = {
    "No.": "number", "no.": "number", "Nos.": "numbers", "p.": "page", "pp.": "pages",
    "fig.": "figure", "Fig.": "figure", "figs.": "figures", "est.": "established",
    "Est.": "established", "vol.": "volume", "Vol.": "volume", "ch.": "chapter",
    "Ch.": "chapter", "sec.": "section", "art.": "article", "Art.": "article",
}  # fmt: skip
# Spelled out letter by letter; other all-capital words are read as words.
INITIALISMS = {
    "FBI", "CIA", "BBC", "CEO", "DNA", "RNA", "USA", "UK", "EU", "UN", "TV", "PC", "IBM",
    "NBC", "CBS", "ABC", "MIT", "UCLA", "NYC", "LA", "DC", "HQ", "ID", "IQ", "MP", "PM",
    "RAF", "IRA", "KGB", "NHS", "BC", "AD", "OK", "BMW", "HIV", "ATM", "PDF", "URL", "GPS",
}  # fmt: skip
# Initialisms that are ordinary words when a whole line is in capitals.
SHOUTABLE_INITIALISMS = {"US"}
ROMAN_CARDINAL_AFTER = {
    "chapter", "part", "book", "volume", "vol", "war", "act", "scene", "section", "phase",
    "article", "psalm", "canto", "stave", "letter", "page", "appendix", "plate", "class",
    "level", "type", "stage", "round", "series", "edition", "number", "no",
}  # fmt: skip
REGNAL_MAX = 30  # the highest regnal number read as "the Nth"
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_value(text: str) -> int | None:
    text = text.upper()
    if not text or any(c not in _ROMAN_VALUES for c in text):
        return None
    total = 0
    for current, nxt in zip(text, text[1:] + " ", strict=True):
        value = _ROMAN_VALUES[current]
        total += -value if nxt != " " and _ROMAN_VALUES[nxt] > value else value
    # Only accept canonical numerals ("IIII" or "IC" aren't numbers here).
    return total if _to_roman(total) == text else None


def _to_roman(n: int) -> str:
    out = ""
    for value, letters in [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]:  # fmt: skip
        while n >= value:
            out += letters
            n -= value
    return out


# --- the rules, applied in order ----------------------------------------------------

_NUM = r"\d{1,3}(?:,\d{3})+|\d+"
_CURRENCY = {
    "$": ("dollar", "dollars", "cent", "cents"),
    "£": ("pound", "pounds", "penny", "pence"),
    "€": ("euro", "euros", "cent", "cents"),
}
_SCALE_WORD = r"(?:\s+(million|billion|trillion|thousand))?"
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"  # noqa: E501
_WORD_AFTER = re.compile(r"\s*([A-Z][a-z]+)")


def _money(match: re.Match) -> str:
    symbol, amount, scale = match.group(1), match.group(2), match.group(3)
    one, many, sub_one, sub_many = _CURRENCY[symbol]
    whole, _, cents = amount.replace(",", "").partition(".")
    if scale:
        return f"{decimal(amount)} {scale} {many}"
    value = int(whole or 0)
    words = f"{cardinal(value)} {one if value == 1 else many}"
    if cents and int(cents):
        c = int(cents.ljust(2, "0")[:2])
        words += f" and {cardinal(c)} {sub_one if c == 1 else sub_many}"
    return words


def _time(match: re.Match) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    if minute == 0:
        return f"{cardinal(hour)} o'clock"
    if minute < 10:
        return f"{cardinal(hour)} oh {cardinal(minute)}"
    return f"{cardinal(hour)} {cardinal(minute)}"


FRACTION_DENOMINATORS = {2, 3, 4, 5, 6, 8, 10, 12, 16, 32, 64, 100}


def _fraction(match: re.Match) -> str:
    """1/2, 3/4, 7/16: fractions. 9/11, 24/7, 50/50, 20/20: two numbers, as said."""
    top, bottom = int(match.group(1)), int(match.group(2))
    if not (0 < top < bottom and bottom in FRACTION_DENOMINATORS):
        return f"{cardinal(top)} {cardinal(bottom)}"
    if bottom == 2:
        name = "half" if top == 1 else "halves"
    elif bottom == 4:
        name = "quarter" if top == 1 else "quarters"
    else:
        name = ordinal(bottom) + ("" if top == 1 else "s")
    return f"{cardinal(top)} {name}"


# A 4-digit number is read as a year only with context: one of these words before it, a
# year before "and"/"to" ("between 1914 and 1918"), the start of a sentence (style guides
# only let a year begin one), the end of a clause ("It was 1945.") or an era after it.
# Otherwise it is a count: "had 1500 soldiers".
_YEAR_CUES = {
    "in", "by", "since", "of", "from", "until", "till", "before", "after", "during",
    "around", "circa", "c", "ca", "year", "summer", "spring", "winter", "autumn", "fall",
    "established", "born", "died", "dated", "early", "late", "mid", "between",
} | {m.lower() for m in MONTHS}  # fmt: skip
_WORD_BEFORE = re.compile(r"([A-Za-z]+)[.,]?\s*$")
_YEAR_LINK = re.compile(r"\b\d{4},?\s+(?:and|or|to|through|until)\s*$")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;][\"'”’)]*\s+)[\"'“‘(]*$")
_CLAUSE_END = re.compile(r"\s*(?:[.,;:!?)\]\"'”’—–]|$)")
_ERA = re.compile(r"\s+(?:A D|B C|C E|B C E)\b")


def _year_cue(string: str, start: int) -> bool:
    """A word that says "year" right before the number ("in 1066", "since 2312")."""
    word = _WORD_BEFORE.search(string[:start])
    return bool(word and word.group(1).lower() in _YEAR_CUES)


def _year_context(string: str, start: int, end: int) -> bool:
    before, after = string[:start], string[end:]
    return bool(
        _year_cue(string, start)
        or _YEAR_LINK.search(before)
        or _SENTENCE_START.search(before)
        or _CLAUSE_END.match(after)
        or _ERA.match(after)
        or before.endswith("A D ")  # "AD 1066", already spelled out
    )


def _number(match: re.Match) -> str:
    text = match.group(0)
    if "," in text or "." in text:
        return decimal(text)
    value = int(text)
    if len(text) == 4:
        # With a cue word ("in 1066", "since 2312") any year 1000-2999 is one; without,
        # only 1100-2099 with other context (counts like "1500 soldiers" are common).
        if 1000 <= value <= 2999 and _year_cue(match.string, match.start()):
            return year(value)
        if is_year(value) and _year_context(match.string, *match.span()):
            return year(value)
    return cardinal(value)


def _slash_date(match: re.Match) -> str:
    """12/25/1990: each number as it stands (day-month order can't be known)."""
    first, second, last = match.groups()
    end = year(int(last)) if len(last) == 4 and is_year(int(last)) else cardinal(int(last))
    return f"{cardinal(int(first))} {cardinal(int(second))} {end}"


def _iso_date(match: re.Match) -> str:
    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if not 1 <= m <= 12 or not 1 <= d <= 31:
        return match.group(0)
    return f"{MONTHS[m - 1]} {ordinal(d)}, {year(y)}"


def _roman(match: re.Match) -> str:
    before, numeral = match.group(1), match.group(2)
    value = roman_value(numeral)
    if value is None:
        return match.group(0)
    if match.string[match.end() : match.end() + 1] == "-":
        return match.group(0)  # "no mix-up", "a CD-ROM": part of a word
    keyword = before.strip().rstrip(".").lower()
    if keyword in ROMAN_CARDINAL_AFTER:
        # A lone "I" after a lowercase keyword is the pronoun when a word follows: "the
        # letter I sent". "Chapter I" and "in volume I." are numerals.
        word_after = re.match(r"\s+\w", match.string[match.end() :])
        if numeral in ("I", "i") and before.strip()[:1].islower() and word_after:
            return match.group(0)
        return f"{before}{cardinal(value)}"
    # "Henry VIII", "John Paul II", "John XXIII": a capitalised name, a numeral of two or
    # more letters (a lone "I" after a name is too often the pronoun), and a number a
    # monarch or pope could have: "Washington DC", "Jane Doe MD" and "Size XL" aren't.
    regnal = before.strip()[:1].isupper() and len(numeral) > 1 and numeral.isupper()
    if regnal and value <= REGNAL_MAX:
        return f"{before}the {ordinal(value).capitalize()}"
    return match.group(0)


def _caps(match: re.Match) -> str:
    word = match.group(0)
    if word in SHOUTABLE_INITIALISMS:
        # "the US" is spelled out, but in an all-capital line ("LET US GO") it's a word.
        around = match.string[max(0, match.start() - 30) : match.end() + 30]
        shouted = len(re.findall(r"\b[A-Z]{2,}\b", around)) > 1
        return word.capitalize() if shouted else " ".join(word)
    if word in INITIALISMS:
        return " ".join(word)
    if roman_value(word) is not None:
        return word  # left for the Roman-numeral rules
    if len(word) <= 3 and not re.search(r"[AEIOUY]", word):
        return " ".join(word)  # no vowel: can't be said as a word ("BBC", "NHS")
    return word.capitalize()


_AMBIGUOUS = sorted(set(TITLES) | set(AFTER_NAME), key=len, reverse=True)
_ABBREVIATION = re.compile(
    r"(\S+\s+)?(" + "|".join(re.escape(a) for a in _AMBIGUOUS) + r")(?=\s|$)(\s+\S+)?"
)


def _abbreviation(match: re.Match) -> str:
    """ "Dr. Jones" -> Doctor, "12 Oak Dr." -> Drive; "St. Paul's" -> Saint, "Baker St." ->
    Street. A capitalised name after it means a title; a capitalised word or number before
    it, with no name after, means the street (or company) word."""
    before, short, after = match.group(1) or "", match.group(2), match.group(3) or ""
    next_word = after.strip()
    sentence_after = not next_word or next_word.strip("\"“'‘(") in SENTENCE_STARTERS
    name_after = bool(re.match(r"\s+[A-Z]", after)) and not sentence_after
    word_before = before.strip()
    named_before = bool(word_before) and (word_before[0].isupper() or word_before[0].isdigit())
    if short in AFTER_NAME and named_before and (not name_after or short not in TITLES):
        long = AFTER_NAME[short]
        if sentence_after:
            long += "."  # "Baker St. The house…": the full stop also ends the sentence
    elif short in TITLES:
        long = TITLES[short]
    else:
        long = AFTER_NAME[short]
    return f"{before}{long}{after}"


def _phrase(long: str):
    def expand(match: re.Match) -> str:
        """Keep the full stop when the abbreviation ends the sentence: "pears, etc. Then"."""
        rest = match.string[match.end() :]
        ends = re.match(r"\s*$", rest) or re.match(r"\s+[\"“‘(]?[A-Z]", rest)
        return long + "." if ends and match.group(0) in SENTENCE_FINAL else long

    return expand


def normalize(text: str) -> str:
    t = text
    # Typographic apostrophes and "rock 'n' roll".
    t = re.sub(r"[‘’]n[‘’]", "and", t)
    t = t.replace("’", "'")
    t = re.sub(r"[   ]", " ", t)

    # Dates before plain numbers.
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _iso_date, t)
    t = re.sub(
        rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,\s*(\d{{4}})\b",
        lambda m: f"{m.group(1)} {ordinal(int(m.group(2)))}, {year(int(m.group(3)))}",
        t,
    )
    t = re.sub(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s+(\d{{4}})\b",
        lambda m: f"the {ordinal(int(m.group(1)))} of {m.group(2)}, {year(int(m.group(3)))}",
        t,
    )
    t = re.sub(
        rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!,?\s*\d)",
        lambda m: f"{m.group(1)} {ordinal(int(m.group(2)))}",
        t,
    )
    t = re.sub(r"(?<![\w'])'(\d{2})\b", lambda m: cardinal(int(m.group(1))), t)  # '68

    # Phrases and abbreviations (before the period-sensitive rules below).
    for short, long in PHRASES.items():
        t = re.sub(rf"(?<!\w){re.escape(short)}(?=\W|$)", _phrase(long), t)
    for short, long in BEFORE_NUMBER.items():
        t = re.sub(rf"(?<!\w){re.escape(short)}\s*(?=\d)", long + " ", t)
    for _ in range(3):  # neighbours ("Lt. Col.") overlap, so repeat until settled
        t, changed = _ABBREVIATION.subn(_abbreviation, t)
        if not changed:
            break
    t = re.sub(r"\b((?:[A-Z]\.){2,})", lambda m: " ".join(m.group(1).replace(".", "")), t)

    # Symbols.
    t = re.sub(r"§\s*(?=\d)", "section ", t)
    t = re.sub(r"#\s*(?=\d)", "number ", t)
    t = t.replace(" & ", " and ")

    # Money, percentages, temperatures, times, fractions, ranges, ordinals, decades.
    t = re.sub(rf"([$£€])\s?((?:{_NUM})(?:\.\d+)?){_SCALE_WORD}", _money, t)
    t = re.sub(r"(\d)\s?%", r"\1 percent", t)
    t = re.sub(r"(?<![\w-])-(?=\d)", "minus ", t)
    t = re.sub(r"\s?°\s?C\b", " degrees Celsius", t)
    t = re.sub(r"\s?°\s?F\b", " degrees Fahrenheit", t)
    t = re.sub(r"\s?°", " degrees", t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, t)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", _slash_date, t)
    t = re.sub(r"(?<![\d/])(\d+)/(\d+)\b(?!/\d)", _fraction, t)
    t = re.sub(r"\b(\d+)\s?[–—-]\s?(\d+)\b", lambda m: f"{m.group(1)} to {m.group(2)}", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), t)
    t = re.sub(
        r"\b(\d{4})s\b",
        lambda m: (
            year(int(m.group(1))).rsplit(" ", 1)[0]
            + " "
            + plural(year(int(m.group(1))).rsplit(" ", 1)[1])
        ),
        t,
    )
    t = re.sub(r"\b(\d0)s\b", lambda m: plural(cardinal(int(m.group(1)))), t)

    # Roman numerals by context, then all-capital words.
    t = re.sub(r"(\b[A-Za-z]+\.?\s+)([IVXLCDM]{1,7}|[ivxlcdm]{1,7})\b(?![\w'])", _roman, t)
    t = re.sub(r"\b[A-Z]{2,}\b", _caps, t)
    # Roman numerals revealed by the caps rule ("BOOK II" -> "Book II").
    t = re.sub(r"(\b[A-Za-z]+\.?\s+)([IVXLCDM]{1,7})\b(?![\w'])", _roman, t)

    # Remaining numbers.
    t = re.sub(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+", _number, t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()
