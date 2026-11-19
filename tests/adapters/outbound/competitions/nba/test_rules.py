"""Tests for the nine categories: one definition, read the same way everywhere."""

import pytest

from thefrontoffice.adapters.outbound.competitions.availability import QUESTIONABLE
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    FIELD_GOALS,
    POINTS,
    SCOUTED,
    THREES,
    TURNOVERS,
    amount,
    chance,
    fantasy_points,
    fits,
    line,
    printed,
    stranded,
)


def test_nine_categories_each_named_once_on_every_platform() -> None:
    assert len(CATEGORIES) == 9
    for name in ("label", "yahoo_stat", "made", "tag"):
        assert len({getattr(c, name) for c in CATEGORIES}) == 9, name


def test_turnovers_are_not_scouted() -> None:
    """Leading the league in turnovers is not a reason to add someone."""
    assert TURNOVERS not in SCOUTED
    assert len(SCOUTED) == 8


def test_nothing_attempted_is_no_percentage_rather_than_zero() -> None:
    assert FIELD_GOALS.figure({"fgm": 0.0}) is None
    assert "FG%" not in line({"pts": 10.0})


def test_a_line_carries_each_percentages_attempts_a_game() -> None:
    figures = line({"fgm": 9.0, "fga": 20.0, "ftm": 4.0, "fta": 6.0}, games=2)

    assert (figures[FIELD_GOALS.attempted], figures["FTA"]) == (10.0, 3.0)
    assert "FTA" not in line({"fgm": 2.0, "fga": 4.0})


def test_a_percentage_reads_as_one() -> None:
    assert FIELD_GOALS.show(0.4823) == "48.2%"
    assert POINTS.show(25.25) == "25.2"


def test_threes_are_tagged_so_the_count_cannot_run_into_the_tag() -> None:
    """ "5" + "3pm" renders as "53pm", which reads as fifty-three."""
    assert THREES.tagged(5.0) == "5.0tpm"
    assert FIELD_GOALS.tagged(0.5) == "FG50.0%"


@pytest.mark.parametrize(
    ("slot", "status", "expected"),
    [
        ("IL", "", True),
        ("IL", "GTD", True),
        ("IL", "DTD", True),
        ("IL", "O", False),
        ("IL", "INJ", False),
        ("IL", "OFS", False),
        ("IL+", "", True),
        ("IL+", "O", False),
        ("IL+", "GTD", False),
        ("IL+", "DTD", False),
        ("BN", "", False),
        ("IL", "SUSP", False),
    ],
)
def test_an_injured_slot_refuses_only_what_yahoos_rules_say_it_refuses(slot: str, status: str, expected: bool) -> None:
    """A status the rules never mention is not flagged: a false "move him" costs more than a late one."""
    assert stranded(slot, status) is expected


# ── a points league ─────────────────────────────────────────────────────

WEIGHTS = {"12": 1.0, "15": 1.2, "16": 1.5, "17": 3.0, "18": 3.0, "19": -1.0}
"""A standard Yahoo points league's weights, by stat id: PTS, REB, AST, STL, BLK, TO."""


def test_fantasy_points_weigh_each_counting_category() -> None:
    figures = {"PTS": 20.0, "REB": 10.0, "AST": 4.0, "STL": 1.0, "BLK": 2.0, "TO": 3.0, "FG%": 0.5}

    assert fantasy_points(figures, WEIGHTS) == pytest.approx(20 + 12 + 6 + 3 + 6 - 3)


def test_an_empty_line_scores_nothing_rather_than_zero() -> None:
    assert fantasy_points({}, WEIGHTS) is None


def test_a_weighted_stat_no_category_counts_leaves_no_score_rather_than_a_partial_one() -> None:
    """Field goals attempted (stat 3) are weighted by some leagues and counted by no category here."""
    assert fantasy_points({"PTS": 20.0}, {"12": 1.0, "3": -0.5}) is None


@pytest.mark.parametrize(
    ("slot", "positions", "takes"),
    [
        ("PG", "PG,SG", True),
        ("C", "PG,SG", False),
        ("G", "SG", True),
        ("F", "PG", False),
        ("FC", "C", True),
        ("Util", "C", True),
        ("Util", "", False),
    ],
)
def test_a_lineup_slot_takes_the_positions_yahoo_lets_into_it(slot: str, positions: str, takes: bool) -> None:
    assert fits(slot, positions) is takes


def test_a_scoreboard_count_is_its_total_and_a_percentage_its_makes_and_attempts() -> None:
    stats = {POINTS.yahoo_stat: "143", FIELD_GOALS.yahoo_shots: "109/218"}

    assert printed(stats, POINTS) == (143.0, 0.0)
    assert printed(stats, FIELD_GOALS) == (109.0, 218.0)


def test_a_figure_not_yet_printed_is_nothing_scored() -> None:
    assert printed({POINTS.yahoo_stat: "-"}, POINTS) == (0.0, 0.0)
    assert printed({}, FIELD_GOALS) == (0.0, 0.0)
    assert amount("") == 0.0


@pytest.mark.parametrize(("status", "expected"), [("", 1.0), ("GTD", QUESTIONABLE), ("dtd", QUESTIONABLE), ("O", 1.0)])
def test_only_a_game_time_decision_is_a_chance_a_ruling_counts_in_his_games(status: str, expected: float) -> None:
    assert chance(status) == expected
