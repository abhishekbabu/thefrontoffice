"""Tests for the shared playoff bracket: `competitions/brackets.py`."""

from thefrontoffice.adapters.outbound.competitions.brackets import lengths, round_name


def test_a_bracket_takes_enough_rounds_for_its_teams_byes_filling_the_first() -> None:
    assert [len(lengths(teams)) for teams in (2, 4, 6, 8, 12)] == [1, 2, 3, 3, 4]


def test_no_bracket_without_two_teams_to_play_it() -> None:
    assert lengths(0) == lengths(1) == []


def test_rounds_last_two_weeks_each_or_only_in_the_final() -> None:
    assert lengths(6, two_week_rounds=True) == [2, 2, 2]
    assert lengths(6, two_week_final=True) == [1, 1, 2]


def test_rounds_are_named_back_from_the_final() -> None:
    rounds = lengths(12)

    assert [round_name(rounds, 15, week) for week in range(15, 19)] == [
        "Round 1",
        "Quarterfinals",
        "Semifinals",
        "Final",
    ]


def test_a_two_week_round_says_which_week_of_it() -> None:
    assert [round_name([1, 2], 20, week) for week in (20, 21, 22)] == [
        "Semifinals",
        "Final, week 1 of 2",
        "Final, week 2 of 2",
    ]


def test_weeks_outside_the_bracket_have_no_round() -> None:
    assert (round_name([1, 1], 19, 18), round_name([1, 1], 19, 21)) == ("", "")
