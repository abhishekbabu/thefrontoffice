"""Tests for a basketball player's worth this week: `nba/worth.py`."""

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, FIELD_GOALS, POINTS, TURNOVERS
from thefrontoffice.adapters.outbound.competitions.nba.worth import (
    MINUTES,
    Reading,
    category_value,
    game_value,
    per_game,
    points_value,
    read,
    scales,
    usage,
    weakest,
)
from thefrontoffice.adapters.outbound.competitions.worth import USAGE_SWING
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory


def _stats(played: int = 10, minutes: tuple[float, ...] = (), **box: float) -> PlayerStats:
    games = [NBAGameLog(player_id="p", date=f"2026-01-{i + 1:02d}", opponent="BOS", stats=box) for i in range(played)]
    stats = PlayerStats(recent=RecentForm(games=played, line=nine_cat(games)))
    if minutes:
        stats["minutes"] = minutes
    return stats


def _scored(*categories: StatCategory) -> list[StatCategory]:
    return list(categories)


def test_a_game_blends_his_run_with_the_projection_a_game() -> None:
    projected = ProjectedTotals(games=2, totals={"pts": 40.0})

    line = per_game(_stats(pts=10), projected)

    assert line is not None
    assert line[POINTS.label] == pytest.approx(15.0)


def test_a_projection_alone_is_read_a_game() -> None:
    line = per_game(None, ProjectedTotals(games=4, totals={"pts": 80.0, "blk": 4.0}))

    assert line is not None
    assert (line[POINTS.label], line[BLOCKS.label]) == (pytest.approx(20.0), pytest.approx(1.0))


def test_nothing_to_read_is_no_line() -> None:
    assert per_game(None, None) is None
    assert per_game(None, ProjectedTotals(games=0, totals={})) is None


def test_a_points_league_values_a_game_in_its_fantasy_points() -> None:
    value = points_value({POINTS.yahoo_stat: 1.0, BLOCKS.yahoo_stat: 3.0})

    assert value({POINTS.label: 20.0, BLOCKS.label: 2.0}) == pytest.approx(26.0)


def test_a_scarce_category_weighs_more_than_a_plentiful_one() -> None:
    """A block is scarcer than a point, so one more of it is worth more of the spread."""
    pool = [{POINTS.label: 10.0, BLOCKS.label: 0.0}, {POINTS.label: 30.0, BLOCKS.label: 2.0}]
    value = category_value(
        _scored(StatCategory(POINTS.yahoo_stat, "PTS"), StatCategory(BLOCKS.yahoo_stat, "BLK")), pool
    )

    one_point = value({POINTS.label: 21.0, BLOCKS.label: 1.0})
    one_block = value({POINTS.label: 20.0, BLOCKS.label: 2.0})

    assert one_point is not None and one_block is not None
    assert one_block > one_point


def test_turnovers_count_against_him() -> None:
    pool = [{TURNOVERS.label: 1.0}, {TURNOVERS.label: 3.0}]
    value = category_value(_scored(StatCategory(TURNOVERS.yahoo_stat, "TO", fewer_wins=True)), pool)

    careless, careful = value({TURNOVERS.label: 4.0}), value({TURNOVERS.label: 1.0})

    assert careless is not None and careful is not None
    assert careless < careful < 0


def test_a_percentage_counts_from_the_pools_average() -> None:
    pool = [{FIELD_GOALS.label: 0.40}, {FIELD_GOALS.label: 0.50}]
    value = category_value(_scored(StatCategory(FIELD_GOALS.yahoo_stat, "FG%")), pool)

    assert value({FIELD_GOALS.label: 0.45}) == pytest.approx(0.0)
    assert (value({FIELD_GOALS.label: 0.50}) or 0) > 0


def test_a_category_this_app_has_no_figure_for_counts_nothing() -> None:
    value = category_value(_scored(StatCategory("27", "DD")), [{POINTS.label: 10.0}, {POINTS.label: 20.0}])

    assert value({POINTS.label: 30.0}) is None


def test_steady_starters_minutes_nudge_him_up() -> None:
    assert usage(_stats(minutes=(34, 33, 35, 32, 36, 20))) == 1 + USAGE_SWING


def test_minutes_that_come_and_go_nudge_him_down() -> None:
    """Newest first: his latest game is not his most, so the swing is not a role growing."""
    assert usage(_stats(minutes=(22, 34, 18, 30, 25))) == 1 - USAGE_SWING


def test_only_his_last_few_games_of_minutes_count() -> None:
    steady, then_benched = (33.0,) * MINUTES.games, (10.0,) * 5

    assert usage(_stats(minutes=steady + then_benched)) == 1 + USAGE_SWING


def test_his_week_is_a_games_value_nudged_by_minutes_times_games_left() -> None:
    reading = Reading(player=make_player("A"), line={}, per_game=20.0, games=3, usage=1.1)

    assert reading.worth == pytest.approx(66.0)
    assert game_value(reading) == pytest.approx(22.0)


@pytest.mark.parametrize(("per", "games"), [(None, 3), (20.0, None)])
def test_a_week_with_either_part_unknown_is_unknown(per: float | None, games: int | None) -> None:
    reading = Reading(player=make_player("A"), line=None, per_game=per, games=games)

    assert reading.worth is None


def test_a_reading_carries_his_line_value_and_minutes() -> None:
    weights = {POINTS.yahoo_stat: 1.0}

    reading = read(make_player("A"), _stats(pts=20, minutes=(30, 20)), None, points_value(weights), 2)

    assert (reading.per_game, reading.games, reading.minutes) == (pytest.approx(20.0), 2, pytest.approx(25.0))
    assert reading.worth == pytest.approx(40.0)


def test_a_player_with_nothing_to_read_has_no_value() -> None:
    reading = read(make_player("A"), None, None, points_value({POINTS.yahoo_stat: 1.0}), 2)

    assert (reading.line, reading.per_game, reading.minutes) == (None, None, None)


SCORED = _scored(
    StatCategory(FIELD_GOALS.yahoo_stat, "FG%"),
    StatCategory(BLOCKS.yahoo_stat, "BLK"),
    StatCategory(POINTS.yahoo_stat, "PTS"),
    StatCategory(TURNOVERS.yahoo_stat, "TO", fewer_wins=True),
)
POOL = [
    {FIELD_GOALS.label: 0.50, BLOCKS.label: 1.0, POINTS.label: 20.0, TURNOVERS.label: 1.0},
    {FIELD_GOALS.label: 0.46, BLOCKS.label: 0.5, POINTS.label: 15.0, TURNOVERS.label: 1.5},
    {FIELD_GOALS.label: 0.42, BLOCKS.label: 0.0, POINTS.label: 10.0, TURNOVERS.label: 2.0},
]


def test_a_player_is_weak_where_he_sits_furthest_under_the_pools_average_worst_first() -> None:
    """A wild shooter who turns it over: those drag him, not the points he scores; more turnovers is worse."""
    line = {FIELD_GOALS.label: 0.38, BLOCKS.label: 0.4, POINTS.label: 18.0, TURNOVERS.label: 3.0}

    assert [c.name for c in weakest(line, scales(SCORED, POOL))] == ["TO", "FG%"]


def test_an_average_line_is_weak_nowhere() -> None:
    assert weakest(POOL[1], scales(SCORED, POOL)) == []
    assert weakest(None, scales(SCORED, POOL)) == []


def test_a_category_with_no_spread_across_the_pool_scales_nothing() -> None:
    assert BLOCKS.label not in scales(SCORED, [{BLOCKS.label: 1.0}, {BLOCKS.label: 1.0}])
