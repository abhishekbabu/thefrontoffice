"""Tests for table places: `competitions/places.py`."""

from thefrontoffice.adapters.outbound.competitions.places import ordinal, place


def test_the_teens_are_all_th_whatever_their_last_digit() -> None:
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 111)] == [
        "1st",
        "2nd",
        "3rd",
        "4th",
        "11th",
        "12th",
        "13th",
        "21st",
        "22nd",
        "111th",
    ]


def test_a_place_says_how_many_it_is_out_of() -> None:
    assert place(5, 14) == "5th of 14"
