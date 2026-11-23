"""Tests for a basketball player's worth this week: `nba/worth.py`."""

from dataclasses import replace

import pytest
from support.nba import FakeSleeperNBA, make_player

from thefrontoffice.adapters.outbound.competitions.nba.form import (
    ROLE_GAMES,
    PlayerStats,
    RecentForm,
    SleeperNBAForm,
    nine_cat,
)
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, FIELD_GOALS, POINTS, TURNOVERS
from thefrontoffice.adapters.outbound.competitions.nba.worth import (
    MINUTES,
    ROLE,
    TARGET_FLOOR,
    Reading,
    Targeting,
    category_value,
    game_value,
    moved,
    per_game,
    points_value,
    read,
    rising,
    scales,
    usage,
    weakest,
    winnable,
)
from thefrontoffice.adapters.outbound.competitions.worth import USAGE_SWING, settled
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


FG = FIELD_GOALS.label
FGA = FIELD_GOALS.attempted


def test_a_percentage_counts_from_the_pools_rate_over_all_its_attempts() -> None:
    """10 attempts at .400 and 10 at .500: the pool shoots .450, so a .450 shooter adds nothing."""
    pool = [{FG: 0.40, FGA: 10.0}, {FG: 0.50, FGA: 10.0}]
    value = category_value(_scored(StatCategory(FIELD_GOALS.yahoo_stat, "FG%")), pool)

    assert value({FG: 0.45, FGA: 12.0}) == pytest.approx(0.0)
    assert (value({FG: 0.50, FGA: 12.0}) or 0) > 0


def test_a_percentage_weighs_by_attempts_so_volume_beats_a_few_makes() -> None:
    """3 for 4 a night moves a team's rate less than 9 for 16 does, though .750 is the better rate."""
    pool = [{FG: 0.40, FGA: 10.0}, {FG: 0.50, FGA: 10.0}, {FG: 0.46, FGA: 15.0}]
    value = category_value(_scored(StatCategory(FIELD_GOALS.yahoo_stat, "FG%")), pool)

    few, many = value({FG: 0.75, FGA: 4.0}), value({FG: 0.5625, FGA: 16.0})

    assert few is not None and many is not None
    assert many > few > 0


def test_a_rate_without_its_attempts_counts_nothing() -> None:
    pool = [{FG: 0.40, FGA: 10.0}, {FG: 0.50, FGA: 10.0}, {POINTS.label: 10.0}]
    value = category_value(
        _scored(StatCategory(FIELD_GOALS.yahoo_stat, "FG%"), StatCategory(POINTS.yahoo_stat, "PTS")), pool
    )

    assert value({FG: 0.60, POINTS.label: 0.0}) == pytest.approx(0.0)


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


def test_what_picking_him_up_is_worth_discounts_a_game_time_decisions_next_game() -> None:
    doubtful = Reading(player=make_player("A", status="GTD"), line={}, per_game=10.0, games=3)

    assert doubtful.available == pytest.approx(28.0)
    assert replace(doubtful, player=make_player("A")).available == pytest.approx(30.0)
    assert replace(doubtful, games=None).available is None


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
    {FG: 0.50, FGA: 12.0, BLOCKS.label: 1.0, POINTS.label: 20.0, TURNOVERS.label: 1.0},
    {FG: 0.46, FGA: 12.0, BLOCKS.label: 0.5, POINTS.label: 15.0, TURNOVERS.label: 1.5},
    {FG: 0.42, FGA: 12.0, BLOCKS.label: 0.0, POINTS.label: 10.0, TURNOVERS.label: 2.0},
]


def test_a_player_is_weak_where_he_sits_furthest_under_the_pools_average_worst_first() -> None:
    """A wild shooter who turns it over: those drag him, not the points he scores; more turnovers is worse."""
    line = {FG: 0.38, FGA: 14.0, BLOCKS.label: 0.4, POINTS.label: 18.0, TURNOVERS.label: 3.0}

    assert [c.name for c in weakest(line, scales(SCORED, POOL))] == ["TO", "FG%"]


def test_a_poor_rate_on_few_attempts_is_no_weakness() -> None:
    line = {FG: 0.30, FGA: 1.0, BLOCKS.label: 0.5, POINTS.label: 15.0, TURNOVERS.label: 1.5}

    assert weakest(line, scales(SCORED, POOL)) == []


def test_an_average_line_is_weak_nowhere() -> None:
    assert weakest(POOL[1], scales(SCORED, POOL)) == []
    assert weakest(None, scales(SCORED, POOL)) == []


def test_a_category_with_no_spread_across_the_pool_scales_nothing() -> None:
    assert BLOCKS.label not in scales(SCORED, [{BLOCKS.label: 1.0}, {BLOCKS.label: 1.0}])


# ── this week's categories, weighed by how winnable each is ─────────


def test_a_category_near_even_counts_in_full_and_a_sure_one_only_to_the_floor() -> None:
    assert winnable(0.5) == pytest.approx(1.0)
    assert winnable(0.25) == pytest.approx(winnable(0.75))
    assert winnable(0.75) < 1.0
    assert winnable(0.99) == winnable(0.0) == TARGET_FLOOR


EVEN = {"FG%": 0.5, "BLK": 0.5, "PTS": 0.5, "TO": 0.5}
BLOCKER = {FG: 0.46, FGA: 12.0, BLOCKS.label: 2.0, POINTS.label: 8.0, TURNOVERS.label: 1.5}
SCORER = {FG: 0.46, FGA: 12.0, BLOCKS.label: 0.0, POINTS.label: 26.0, TURNOVERS.label: 1.5}


def test_at_even_odds_everywhere_a_game_this_week_is_his_value_a_game() -> None:
    even = Targeting.of(scales(SCORED, POOL), EVEN)

    assert even.value(BLOCKER) == pytest.approx(category_value(SCORED, POOL)(BLOCKER))


def test_a_game_this_week_weighs_each_category_by_how_winnable_it_is() -> None:
    """Blocks all but won and points even: the scorer outweighs the blocker this week, not over a season."""
    found = scales(SCORED, POOL)
    even = Targeting.of(found, EVEN)
    targeted = Targeting.of(found, {**EVEN, "BLK": 0.98})

    assert (even.value(BLOCKER) or 0) > (even.value(SCORER) or 0)
    assert (targeted.value(SCORER) or 0) > (targeted.value(BLOCKER) or 0)


def test_a_sure_category_still_counts_for_something() -> None:
    found = scales(SCORED, POOL)
    sure = Targeting.of(found, dict.fromkeys(EVEN, 1.0))

    assert sure.value(POOL[0]) == pytest.approx(TARGET_FLOOR * (category_value(SCORED, POOL)(POOL[0]) or 0))


def test_the_targets_are_the_close_categories_a_pickup_adds_most_to_over_the_drop() -> None:
    """Points are all but won and FG% all but lost, so neither is a target; blocks and turnovers are close."""
    targeting = Targeting.of(scales(SCORED, POOL), {"FG%": 0.05, "BLK": 0.5, "PTS": 0.98, "TO": 0.45})
    pickup = {FG: 0.50, FGA: 12.0, BLOCKS.label: 2.0, POINTS.label: 25.0, TURNOVERS.label: 0.5}
    drop = {FG: 0.40, FGA: 12.0, BLOCKS.label: 0.0, POINTS.label: 10.0, TURNOVERS.label: 2.5}

    assert targeting.targets(pickup, drop) == ["BLK", "TO"]
    assert targeting.targets(None, drop) == []
    assert targeting.value(None) is None


# ── a role that has moved ───────────────────────────────────────────────


def _career(*runs: tuple[int, float, float]) -> PlayerStats:
    """His form, read by Sleeper's reader from runs of (games, minutes, points), oldest run first."""
    played = [(minutes, pts) for games, minutes, pts in runs for _ in range(games)]
    logs = [
        NBAGameLog(player_id="p1", date=f"2026-11-{day + 1:02d}", opponent="BOS", stats={"pts": pts}, minutes=minutes)
        for day, (minutes, pts) in enumerate(played)
    ]
    stats = SleeperNBAForm(FakeSleeperNBA(logs={"p1": logs[::-1]}), season="2026").get_player_stats("Nikola Jokic")
    assert stats is not None
    return stats


def _points(stats: PlayerStats) -> float:
    line = per_game(stats, None)
    assert line is not None
    return line[POINTS.label]


STEADY = _career((15, 30.0, 13.0))


def test_a_riser_outranks_a_steadier_player_with_a_better_window() -> None:
    """Handed a starter's minutes five games ago: fifteen games average his new role away."""
    riser = _career((10, 25.0, 8.0), (5, 38.0, 22.0))

    assert riser["recent"].line[POINTS.label] < STEADY["recent"].line[POINTS.label]
    assert _points(riser) > _points(STEADY)


def test_a_riser_is_pulled_toward_his_last_five_only_as_far_as_they_have_settled() -> None:
    riser = _career((10, 25.0, 8.0), (5, 38.0, 22.0))
    window = riser["recent"].line[POINTS.label]

    pull = settled(ROLE_GAMES, ROLE.settling)
    assert _points(riser) == pytest.approx(window + pull * (22.0 - window))
    assert _points(riser) < 22.0


def test_a_faller_drops_below_a_steadier_player_his_window_beats() -> None:
    faller = _career((10, 32.0, 18.0), (5, 20.0, 6.0))

    assert faller["recent"].line[POINTS.label] > STEADY["recent"].line[POINTS.label]
    assert _points(faller) < _points(STEADY)


def test_one_big_night_on_steady_minutes_is_no_new_role() -> None:
    """Points without the minutes behind them: the night counts its share of the run, and no more."""
    outlier = _career((14, 30.0, 13.0), (1, 30.0, 45.0))

    assert _points(outlier) == pytest.approx((14 * 13 + 45) / 15)


def test_one_long_night_does_not_move_a_role() -> None:
    """An overtime game lifts his last five's minutes by a fraction of the move a role needs."""
    overtime = _career((14, 30.0, 13.0), (1, 45.0, 30.0))

    assert not moved(overtime["role"])
    assert not rising(overtime)
    assert _points(overtime) == pytest.approx(overtime["recent"].line[POINTS.label])


def test_a_reading_carries_his_role_for_the_wire_to_show() -> None:
    riser = _career((10, 25.0, 8.0), (5, 38.0, 22.0))

    reading = read(make_player("A"), riser, None, points_value({POINTS.yahoo_stat: 1.0}), 3)

    assert reading.role == (ROLE_GAMES, 38.0, pytest.approx((10 * 25 + 5 * 38) / 15))
    assert moved(reading.role)
    assert not moved(None)


def test_two_games_of_new_minutes_pull_his_line_before_his_last_five_move_by_a_role() -> None:
    """Twenty a night, then 26 twice: his last five are up under three, but his role is growing now."""
    grower = _career((13, 20.0, 8.0), (2, 26.0, 16.0))
    reading = read(make_player("A"), grower, None, points_value({POINTS.yahoo_stat: 1.0}), 3)

    assert not moved(grower["role"])
    assert rising(grower) and reading.rising
    assert _points(grower) > grower["recent"].line[POINTS.label]


def test_the_game_a_player_ruled_out_got_hurt_in_says_nothing_of_his_role() -> None:
    """Thirty a night, then twelve the night he went down: a swing for a healthy player, none for one out."""
    stats = PlayerStats(minutes=(12.0, 30.0, 31.0, 29.0, 32.0, 30.0))

    assert usage(stats) == 1 - USAGE_SWING
    assert usage(stats, hurt=True) == 1.0
    # A short night earlier in the run, not his latest, is still a swing.
    assert usage(PlayerStats(minutes=(30.0, 31.0, 29.0, 12.0, 32.0)), hurt=True) == 1 - USAGE_SWING
