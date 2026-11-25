"""Tests for how every competition combines form, outlook and usage into a worth: `competitions/worth.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.worth import (
    CALL_FORM,
    FORM_WEIGHT,
    USAGE_SWING,
    blend,
    call,
    settled,
    sustained,
    usage,
)


def test_form_and_outlook_blend_by_the_form_weight() -> None:
    assert blend(10.0, 20.0) == pytest.approx(FORM_WEIGHT * 10 + (1 - FORM_WEIGHT) * 20)


@pytest.mark.parametrize(("recent", "ahead", "expected"), [(10.0, None, 10.0), (None, 20.0, 20.0), (None, None, None)])
def test_either_stands_alone_where_the_other_is_unknown(
    recent: float | None, ahead: float | None, expected: float | None
) -> None:
    assert blend(recent, ahead) == expected


def _usage(readings: list[float], grew: bool = False) -> float:
    return usage(readings, steady_from=30, swings_by=10, fewest=3, grew=grew)


def test_a_steady_large_share_in_every_game_is_worth_more() -> None:
    assert _usage([31, 34, 30]) == 1 + USAGE_SWING


def test_a_share_that_swings_is_worth_less() -> None:
    assert _usage([32, 18, 25]) == 1 - USAGE_SWING


def test_a_swing_up_to_his_most_in_his_latest_game_is_a_role_growing_not_a_cut() -> None:
    assert _usage([12, 18, 26]) == 1.0


def test_a_trend_the_caller_knows_of_spares_a_swing() -> None:
    assert _usage([32, 18, 25], grew=True) == 1.0


def test_too_few_games_say_nothing() -> None:
    assert _usage([35, 36]) == 1.0


def test_games_in_a_new_role_count_by_how_many_there_are() -> None:
    """As many games as it takes to settle count for half; one counts for a fraction."""
    assert settled(4, 4) == pytest.approx(0.5)
    assert settled(1, 4) == pytest.approx(0.2)
    assert settled(0, 4) == 0.0


def test_a_form_call_weighs_form_three_to_one_against_the_outlook() -> None:
    assert call(4.0, 12.0) == pytest.approx(CALL_FORM * 4.0 + (1 - CALL_FORM) * 12.0) == pytest.approx(6.0)


def test_a_run_under_a_share_below_one_holds_without_its_worst_game_on_average_and_in_all_but_the_spare() -> None:
    lines = [10.0] * 4

    assert sustained([5.0, 5.0, 5.0, 0.0], lines, 0.6)
    assert not sustained([5.0, 5.0, 9.0, 0.0], lines, 0.6)  # one zero is not a slump: 6.3 without it
    assert not sustained([5.0, 5.0, 9.0, 9.0], lines, 0.6)  # one of the three left under the bar, with one spare
    assert sustained([5.0, 5.0, 9.0, 9.0], lines, 0.8, spare=2)
    assert not sustained([0.0, 0.0, 0.0, 30.0], lines, 0.6)  # bad games, but not on average


def test_a_run_over_a_share_above_one_holds_without_its_best_game() -> None:
    assert sustained([15.0, 16.0, 15.0, 13.0], [10.0] * 4, 1.4)
    assert not sustained([30.0, 15.0, 15.0, 9.0], [10.0] * 4, 1.4)  # one big night: 13.0 without it


def test_no_games_or_a_line_short_of_them_is_no_run() -> None:
    assert not sustained([], [], 0.6)
    assert not sustained([1.0, 1.0], [10.0], 0.6)
