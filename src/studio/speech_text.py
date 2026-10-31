"""The anchor's lines rewritten as words MMS-TTS can say, and cut at commas into phrases.

MMS's English vocabulary is lowercase letters, an apostrophe, a hyphen and a few digits: it drops
punctuation, "%", "$" and decimal points, so "$2.4m, up 40%" reached the voice as "24m up 40",
one breathless run-on. Here numbers, money, percentages, years and acronyms become words, and
each comma or dash becomes a phrase boundary, voiced separately with a short pause between
(tts.py). Plain string rules, no model.
"""

from __future__ import annotations

import re

_ONES = [
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
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")]
_LETTERS = {
    "a": "ay", "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "eff", "g": "jee",
    "h": "aitch", "i": "eye", "j": "jay", "k": "kay", "l": "el", "m": "em", "n": "en", "o": "oh",
    "p": "pee", "q": "cue", "r": "ar", "s": "ess", "t": "tee", "u": "you", "v": "vee",
    "w": "double you", "x": "ex", "y": "why", "z": "zed",
}  # fmt: skip
# Acronyms said as words, not letters.
_SAID_AS_WORDS = {"NASA", "NATO", "OPEC", "COVID", "FIFA", "UNESCO", "SPAC", "ESG", "GAAP"}
_SAID_AS_WORDS -= {"ESG"}  # E-S-G is spelled out
_SUFFIX = {"k": "thousand", "m": "million", "mn": "million", "bn": "billion", "b": "billion",
           "tn": "trillion", "t": "trillion"}  # fmt: skip
_CURRENCY = {"$": "dollars", "£": "pounds", "€": "euros", "¥": "yen"}


def number(n: int) -> str:
    if n < 0:
        return "minus " + number(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" and " + number(r) if r else "")
    for size, name in _SCALES:
        if n >= size:
            big, r = divmod(n, size)
            rest = "" if not r else (" and " if r < 100 else " ") + number(r)
            return number(big) + " " + name + rest
    return str(n)


def year(n: int) -> str:
    if n % 1000 < 10:  # 2005: two thousand and five
        return number(n)
    hi, lo = divmod(n, 100)
    return number(hi) + " " + ("hundred" if lo == 0 else ("oh " if lo < 10 else "") + number(lo))


def decimal(text: str) -> str:
    whole, _, frac = text.partition(".")
    words = number(int(whole.replace(",", "") or 0))
    if frac:
        words += " point " + " ".join(_ONES[int(d)] for d in frac)
    return words


def _money(m: re.Match) -> str:
    cur, amount, suffix = m.group(1), m.group(2), (m.group(3) or "").lower()
    words = decimal(amount)
    if suffix:
        words += " " + _SUFFIX[suffix]
    return f"{words} {_CURRENCY[cur]}"


def _plain_number(m: re.Match) -> str:
    raw, suffix = m.group(1), (m.group(2) or "").lower()
    digits = raw.replace(",", "")
    if suffix == "" and "." not in digits and "," not in raw and 1100 <= int(digits) <= 2099:
        return year(int(digits))
    words = decimal(digits)
    if suffix in _SUFFIX:
        words += " " + _SUFFIX[suffix]
    return words


def _acronym(m: re.Match) -> str:
    word = m.group(0)
    plural = word.endswith("s") and word[:-1].isupper()
    core = word[:-1] if plural else word
    if core in _SAID_AS_WORDS:
        return core.lower() + ("s" if plural else "")
    spelled = " ".join(_LETTERS[c] for c in core.lower())
    return spelled + ("s" if plural else "")


def to_speech(text: str) -> str:
    """One line, written for the ear: every number and symbol as words."""
    t = text.replace("’", "'").replace("—", ", ").replace("–", ", ")
    # The brand, as said on air: "eye oh markets", never "eomarkets" (operator, Oct 31).
    t = re.sub(
        r"\bIoMarkets(?:\.tv|\.TV| TV)?\b",
        lambda m: "eye oh markets" + (" tee vee" if len(m.group(0)) > 9 else ""),
        t,
        flags=re.I,
    )  # noqa: E501
    t = re.sub(
        r"\bQ([1-4])\b",
        lambda m: "the " + ["first", "second", "third", "fourth"][int(m.group(1)) - 1] + " quarter",
        t,
    )  # noqa: E501
    t = re.sub(r"\bFY ?'?(\d{2})\b", lambda m: "fiscal twenty " + number(int(m.group(1))), t)
    t = re.sub(
        r"([$£€¥])\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s?(bn|mn|tn|[kmbt])\b)?",
        _money,
        t,
        flags=re.I,
    )
    t = re.sub(
        r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?%",
        lambda m: decimal(m.group(1).replace(",", "")) + " percent",
        t,
    )  # noqa: E501
    t = re.sub(r"(\d+)(st|nd|rd|th)\b", lambda m: _ordinal(int(m.group(1))), t)
    t = re.sub(
        r"\b((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s?(bn|mn|tn|k)\b)?",
        _plain_number,
        t,
        flags=re.I,
    )
    t = re.sub(r"\b[A-Z]{2,5}s?\b", _acronym, t)
    t = t.replace("&", " and ").replace("+", " plus ").replace("/", " ")
    return re.sub(r"\s+", " ", t).strip()


def _ordinal(n: int) -> str:
    special = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth",
               12: "twelfth"}  # fmt: skip
    if n in special:
        return special[n]
    words = number(n)
    if words.endswith("y"):
        return words[:-1] + "ieth"
    last = words.split("-")[-1].split(" ")[-1]
    if (k := _ONES.index(last) if last in _ONES else -1) in special:
        return words[: -len(last)] + special[k]
    return words + "th"


def phrases(text: str) -> list[str]:
    """`text` for the ear, cut at commas, semicolons and colons: each phrase is voiced alone,
    so the pause the punctuation asked for is really there."""
    spoken = to_speech(text)
    parts = [p.strip() for p in re.split(r"[,;:]\s*", spoken)]
    return [p for p in parts if re.search(r"[a-z]", p, re.I)]
