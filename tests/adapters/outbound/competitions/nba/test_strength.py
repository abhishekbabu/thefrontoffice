"""Tests for a basketball roster's week to come: `nba/strength.py`."""

from dataclasses import replace
from datetime import date

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    BLOCKS,
    CATEGORIES,
    FIELD_GOALS,
    POINTS,
    TURNOVERS,
)
from thefrontoffice.adapters.outbound.competitions.nba.strength import (
    ATTEMPTS,
    FITTED,
    SWINGS,
    Profile,
    Scored,
    Totals,
    Uncertainty,
    banked,
    category_chances,
    hermite,
    loadings,
    nights,
    points_spread,
    profile,
    scored,
    started,
    week_chances,
    week_totals,
)
from thefrontoffice.adapters.outbound.competitions.nba.strength import (
    POINTS as FANTASY,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, StatCategory
from thefrontoffice.domain.errors import UnsupportedError

BLK = Scored(BLOCKS.label)
FG = Scored(FIELD_GOALS.label, percentage=True)
TO = Scored(TURNOVERS.label, fewer_wins=True)


def _reading(line: dict[str, float], per_game: float = 10.0, usage: float = 1.0) -> Reading:
    return Reading(player=make_player("A"), line=line, per_game=per_game, games=3, usage=usage)


def _game(day: int, **box: float) -> NBAGameLog:
    return NBAGameLog(player_id="p", date=f"2026-11-{day:02d}", opponent="BOS", stats=box)


DAY = [date(2026, 12, d) for d in range(1, 8)]

EXACT = Uncertainty(missed=0.0, form={}, rate={}, game={})
"""A week that is exactly its games: no game missed, no line regressed, nothing beyond each game's swing."""


# ── what a game of him gives ────────────────────────────────────────────


def test_a_points_game_is_his_fantasy_points_nudged_by_his_minutes() -> None:
    found = profile(_reading({POINTS.label: 20.0}, per_game=30.0, usage=1.1), [], {POINTS.yahoo_stat: 1.0})

    assert found.mean[FANTASY] == pytest.approx(33.0)
    assert found.value == pytest.approx(33.0)


def test_a_points_game_varies_as_his_own_nights_did() -> None:
    games = [_game(d, pts=p) for d, p in ((1, 10), (2, 20), (3, 30))]

    found = profile(_reading({POINTS.label: 20.0}, per_game=20.0), games, {POINTS.yahoo_stat: 1.0})

    assert found.variance[FANTASY] == pytest.approx(200 / 3)


def test_too_few_nights_of_his_own_vary_by_the_usual_share_in_that_category() -> None:
    found = profile(_reading({BLOCKS.label: 2.0}), [_game(1, blk=2)], None)

    assert found.variance[BLOCKS.label] == pytest.approx((FITTED.game[BLOCKS.label] * 2.0) ** 2)


def test_a_percentage_game_is_his_makes_out_of_the_shots_he_has_been_taking() -> None:
    games = [_game(d, fgm=6, fga=12) for d in (1, 2, 3)]

    found = profile(_reading({FIELD_GOALS.label: 0.5}), games, None)

    assert (found.attempts[FIELD_GOALS.label], found.mean[FIELD_GOALS.label]) == (12.0, 6.0)
    assert found.variance[FIELD_GOALS.label] == pytest.approx(0.25 * 12)


def test_a_shooter_without_games_of_his_own_takes_a_rotation_players_shots() -> None:
    found = profile(_reading({FIELD_GOALS.label: 0.5}), [], None)

    assert found.attempts[FIELD_GOALS.label] == ATTEMPTS[FIELD_GOALS.label]


def test_a_category_no_box_score_counts_is_refused() -> None:
    with pytest.raises(UnsupportedError):
        scored([StatCategory("27", "DD")])


def test_the_leagues_categories_are_compared_as_it_scores_them() -> None:
    found = scored([StatCategory(c.yahoo_stat, c.label, fewer_wins=c is TURNOVERS) for c in CATEGORIES])

    assert Scored(FIELD_GOALS.label, percentage=True) in found
    assert Scored(TURNOVERS.label, fewer_wins=True) in found


# ── the nights a lineup starts ──────────────────────────────────────────


def _games(*days: int, club: str = "LAL") -> list[ScheduledGame]:
    return [ScheduledGame(week=1, date=DAY[d - 1].isoformat(), home=club, away="BOS") for d in days]


def test_a_player_plays_his_clubs_nights() -> None:
    assert nights(make_player("A", team="lal"), _games(1, 3), None) == [DAY[0], DAY[2]]


def test_a_player_ruled_out_plays_only_from_the_day_he_is_back() -> None:
    hurt = make_player("A", status="O")

    assert nights(hurt, _games(1, 3, 5), DAY[2]) == [DAY[2], DAY[4]]
    assert nights(hurt, _games(1, 3, 5), None) == []


def test_a_player_on_waivers_plays_only_the_nights_from_the_day_he_clears_them() -> None:
    waiting = make_player("A", waiver_date=DAY[3])

    assert nights(waiting, _games(1, 3, 4, 5), None) == [DAY[3], DAY[4]]


def test_a_player_on_waivers_and_ruled_out_plays_from_whichever_comes_later() -> None:
    both = make_player("A", status="O", waiver_date=DAY[0])

    assert nights(both, _games(1, 2, 3, 5), DAY[2]) == [DAY[2], DAY[4]]
    assert nights(both, _games(1, 2, 3, 5), None) == []


def test_each_night_starts_the_best_who_play_up_to_the_slots() -> None:
    days = {"best": frozenset(DAY[:2]), "next": frozenset(DAY[:2]), "third": frozenset(DAY[:3])}

    assert started(["best", "next", "third"], days, slots=2) == {"best": 2, "next": 2, "third": 1}


def test_without_slots_everybody_who_plays_starts() -> None:
    days = {"a": frozenset(DAY[:2]), "b": frozenset(DAY[:2])}

    assert started(["a", "b"], days, slots=0) == {"a": 2, "b": 2}


def test_a_lineup_set_for_the_week_plays_its_starters_every_game_and_nobody_else() -> None:
    """The best who play that week are set, a player with no games passed over for one who has them."""
    days = {"idle": frozenset(), "a": frozenset(DAY[:3]), "b": frozenset(DAY[:4])}

    assert started(["idle", "a", "b"], days, slots=1, weekly=True) == {"a": 3}


# ── what a week adds up to ──────────────────────────────────────────────


def test_a_week_sums_each_players_games() -> None:
    profiles = {
        "a": Profile(value=1, mean={BLOCKS.label: 2.0}, variance={BLOCKS.label: 1.0}),
        "b": Profile(value=1, mean={BLOCKS.label: 1.0}, variance={BLOCKS.label: 1.0}),
    }

    totals = week_totals({"a": 3, "b": 2, "nobody": 4}, profiles, EXACT)

    assert totals.mean[BLOCKS.label] == 8.0


def test_a_week_expects_the_games_a_player_will_miss() -> None:
    profiles = {"a": Profile(value=1, mean={BLOCKS.label: 2.0}, variance={BLOCKS.label: 1.0})}

    totals = week_totals({"a": 4}, profiles, Uncertainty(missed=0.25, form={}, rate={}, game={}))

    assert totals.mean[BLOCKS.label] == pytest.approx(4 * 0.75 * 2.0)


def test_the_hand_set_spreads_expected_every_game_played() -> None:
    profiles = {"a": Profile(value=1, mean={BLOCKS.label: 2.0}, variance={BLOCKS.label: 1.0})}

    totals = week_totals({"a": 4}, profiles, Uncertainty(missed=0.25, form={}, rate={}, game={}, discounted=False))

    assert totals.mean[BLOCKS.label] == pytest.approx(8.0)


def test_a_line_far_from_the_typical_players_is_drawn_toward_it_as_far_as_weeks_bore_out() -> None:
    profiles = {"a": Profile(value=1, mean={BLOCKS.label: 3.0}, variance={BLOCKS.label: 1.0})}
    regressed = replace(EXACT, typical={BLOCKS.label: 1.0}, kept={BLOCKS.label: 0.5})

    assert week_totals({"a": 2}, profiles, regressed).mean[BLOCKS.label] == pytest.approx(2 * 2.0)


def test_a_percentage_is_drawn_toward_the_typical_rate_on_the_shots_he_takes() -> None:
    shooter = Profile(
        value=1, mean={FIELD_GOALS.label: 6.0}, variance={FIELD_GOALS.label: 3.0}, attempts={FIELD_GOALS.label: 10.0}
    )
    regressed = replace(EXACT, typical={FIELD_GOALS.label: 0.5}, kept={FIELD_GOALS.label: 0.5})

    totals = week_totals({"a": 1}, {"a": shooter}, regressed)

    assert (totals.mean[FIELD_GOALS.label], totals.attempts[FIELD_GOALS.label]) == pytest.approx((5.5, 10.0))


def test_a_weeks_spread_carries_form_and_unforeseen_nights_beyond_each_games() -> None:
    profiles = {"a": Profile(value=1, mean={BLOCKS.label: 2.0}, variance={BLOCKS.label: 1.0})}

    assert week_totals({"a": 3}, profiles).variance[BLOCKS.label] > 3 * 1.0
    assert week_totals({"a": 3}, profiles, EXACT).variance[BLOCKS.label] == 3 * 1.0


def test_a_points_weeks_spread_is_its_variance_rooted() -> None:
    assert points_spread(Totals(variance={FANTASY: 400.0})) == 20.0


def test_what_is_banked_is_certain() -> None:
    week = Totals(mean={BLOCKS.label: 5.0}, variance={BLOCKS.label: 4.0}).plus(Totals(mean={BLOCKS.label: 7.0}))

    assert (week.mean[BLOCKS.label], week.variance[BLOCKS.label]) == (12.0, 4.0)


def test_the_board_is_read_category_by_category_a_percentage_from_its_shots() -> None:
    side = MatchupSide(
        team_key="t1", name="Mine", stats={BLOCKS.yahoo_stat: "12", FIELD_GOALS.yahoo_shots: "109/218"}, points="-"
    )

    totals = banked(side, [BLK, FG], points=False)

    assert totals.mean == {BLOCKS.label: 12.0, FIELD_GOALS.label: 109.0}
    assert totals.attempts == {FIELD_GOALS.label: 218.0}
    assert banked(side, [], points=True).mean == {FANTASY: 0.0}


def test_a_weeks_percentage_is_its_makes_over_its_attempts_summed() -> None:
    shooter = Profile(
        value=1, mean={FIELD_GOALS.label: 6.0}, variance={FIELD_GOALS.label: 3.0}, attempts={FIELD_GOALS.label: 12.0}
    )

    totals = week_totals({"a": 3}, {"a": shooter}, replace(EXACT, rate={FIELD_GOALS.label: 0.05}))

    assert (totals.mean[FIELD_GOALS.label], totals.attempts[FIELD_GOALS.label]) == (18.0, 36.0)
    assert totals.variance[FIELD_GOALS.label] > 3 * 3.0


# ── who takes a category, and the week ──────────────────────────────────


def test_the_side_ahead_in_a_count_is_favoured_to_take_it() -> None:
    mine = Totals(mean={BLOCKS.label: 30.0}, variance={BLOCKS.label: 25.0})
    theirs = Totals(mean={BLOCKS.label: 20.0}, variance={BLOCKS.label: 25.0})

    [chance] = category_chances(mine, theirs, [BLK])

    assert 0.9 < chance < 1.0


def test_fewer_turnovers_take_the_category() -> None:
    mine = Totals(mean={TURNOVERS.label: 10.0}, variance={TURNOVERS.label: 4.0})
    theirs = Totals(mean={TURNOVERS.label: 20.0}, variance={TURNOVERS.label: 4.0})

    assert category_chances(mine, theirs, [TO])[0] > 0.99


def test_a_percentage_is_compared_as_makes_over_attempts() -> None:
    """More makes on far more shots is the worse percentage."""
    mine = Totals(
        mean={FIELD_GOALS.label: 100.0}, variance={FIELD_GOALS.label: 50.0}, attempts={FIELD_GOALS.label: 200.0}
    )
    theirs = Totals(
        mean={FIELD_GOALS.label: 120.0}, variance={FIELD_GOALS.label: 60.0}, attempts={FIELD_GOALS.label: 300.0}
    )

    assert category_chances(mine, theirs, [FG])[0] > 0.9


def test_a_side_that_takes_no_shots_has_no_percentage_to_win_with() -> None:
    shooting = Totals(mean={FIELD_GOALS.label: 10.0}, attempts={FIELD_GOALS.label: 20.0})

    assert category_chances(Totals(), shooting, [FG]) == [0.0]
    assert category_chances(Totals(), Totals(), [FG]) == [0.5]


def test_a_certain_week_is_certain() -> None:
    level = Totals(mean={BLOCKS.label: 3.0})

    assert category_chances(Totals(mean={BLOCKS.label: 4.0}), level, [BLK]) == [1.0]
    assert category_chances(level, level, [BLK]) == [0.5]


def test_a_week_goes_to_whoever_takes_more_than_half() -> None:
    assert week_chances([1.0, 1.0, 0.0]) == (1.0, 0.0)
    assert week_chances([0.5, 0.5, 0.5]) == pytest.approx((0.5, 0.5))


def test_an_even_split_of_an_even_number_is_a_draw() -> None:
    win, loss = week_chances([1.0, 0.0])

    assert (win, loss) == (0.0, 0.0)


# ── categories that move together ───────────────────────────────────────


def test_a_category_won_by_less_moves_against_the_swing_the_rest_share() -> None:
    """A week a roster plays more lifts its turnovers with its points: good for one, bad for the other."""
    together = loadings([Scored(BLOCKS.label), TO], FITTED)

    assert together == (FITTED.loadings[BLOCKS.label], -FITTED.loadings[TURNOVERS.label])


def test_a_favourite_in_every_category_is_less_sure_of_the_week_when_they_move_together() -> None:
    chances = [0.7] * 9

    alone, _ = week_chances(chances)
    together, _ = week_chances(chances, [0.6] * 9)

    assert together < alone - 0.05


def test_categories_moving_together_leave_each_ones_chance_as_it_was() -> None:
    """Weighed over the shared swing, one category's chance is what it was alone: only the week's changes."""
    for chance in (0.2, 0.5, 0.9):
        win, loss = week_chances([chance], [0.8])

        assert (win, loss) == pytest.approx((chance, 1 - chance), abs=1e-4)


def test_no_loadings_is_independent_categories() -> None:
    chances = [0.6, 0.3, 0.8, 0.55, 0.45]

    assert week_chances(chances, [0.0] * 5) == week_chances(chances)


def test_a_certain_category_stays_certain_whatever_the_swing() -> None:
    assert week_chances([1.0, 1.0, 0.0], [0.9, 0.9, 0.9]) == pytest.approx((1.0, 0.0))


def test_the_swing_is_read_at_levels_that_hold_a_standard_normal() -> None:
    """Weights summing to one, mean nought, variance one, and a normal's fourth moment of three."""
    for nodes in (SWINGS, hermite(7)):
        assert sum(w for _, w in nodes) == pytest.approx(1.0)
        assert sum(w * x for x, w in nodes) == pytest.approx(0.0, abs=1e-12)
        assert sum(w * x**2 for x, w in nodes) == pytest.approx(1.0)
        assert sum(w * x**4 for x, w in nodes) == pytest.approx(3.0)
