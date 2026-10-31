from studio.speech_text import number, phrases, to_speech, year


def test_numbers_and_years():
    assert number(1250) == "one thousand two hundred and fifty"
    assert number(42) == "forty-two"
    assert year(2026) == "twenty twenty-six"
    assert year(2008) == "two thousand and eight"
    assert year(1999) == "nineteen ninety-nine"


def test_money_percent_acronyms_quarters():
    assert to_speech("up 40% to $2.4m") == "up forty percent to two point four million dollars"
    assert to_speech("£22bn") == "twenty-two billion pounds"
    assert to_speech("the CEO and NASA") == "the see ee oh and nasa"
    assert to_speech("in Q3 of FY26") == "in the third quarter of fiscal twenty twenty-six"
    assert to_speech("the 21st season") == "the twenty-first season"
    assert to_speech("in 2025, 300k staff") == "in twenty twenty-five, three hundred thousand staff"


def test_phrases_cut_at_commas_and_dashes():
    assert phrases("You said 40%, but filings — show less.") == [
        "You said forty percent",
        "but filings",
        "show less.",
    ]
    assert phrases("...") == []
