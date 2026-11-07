"""Tests for the nine categories: one definition, read the same way everywhere."""

import pytest

from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    FIELD_GOALS,
    POINTS,
    SCOUTED,
    THREES,
    TURNOVERS,
    line,
)


def test_nine_categories_each_named_once_on_every_platform() -> None:
    assert len(CATEGORIES) == 9
    for name in ("label", "yahoo_stat", "made", "tag"):
        assert len({getattr(c, name) for c in CATEGORIES}) == 9, name


def test_turnovers_are_not_scouted() -> None:
    """Leading the league in turnovers is not a reason to add someone."""
    assert TURNOVERS not in SCOUTED
    assert len(SCOUTED) == 8


def test_a_count_is_averaged_over_the_games_given() -> None:
    assert POINTS.figure({"pts": 45.0}, games=3) == 15.0


def test_a_percentage_is_summed_makes_over_summed_attempts() -> None:
    assert FIELD_GOALS.figure({"fgm": 3.0, "fga": 11.0}, games=2) == pytest.approx(3 / 11)


def test_nothing_attempted_is_no_percentage_rather_than_zero() -> None:
    assert FIELD_GOALS.figure({"fgm": 0.0}) is None
    assert "FG%" not in line({"pts": 10.0})


def test_an_absent_count_is_nought() -> None:
    """Sleeper omits a key rather than publishing a zero."""
    assert line({})["STL"] == 0.0


def test_a_percentage_reads_as_one() -> None:
    assert FIELD_GOALS.show(0.4823) == "48.2%"
    assert POINTS.show(25.25) == "25.2"


def test_threes_are_tagged_so_the_count_cannot_run_into_the_tag() -> None:
    """ "5" + "3pm" renders as "53pm", which reads as fifty-three."""
    assert THREES.tagged(5.0) == "5.0tpm"
    assert FIELD_GOALS.tagged(0.5) == "FG50.0%"
