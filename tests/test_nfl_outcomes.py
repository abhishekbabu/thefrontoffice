"""Tests for each football player's range of outcomes: `nfl/outcomes.py`."""

from dataclasses import replace
from statistics import pstdev

import pytest
from conftest import _proj

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.outcomes import (
    PLAYS,
    UNDER_WAY,
    Spreads,
    outcomes,
    spreads,
)


def _evidence(**games: tuple[tuple[float, ...], str]) -> Evidence:
    return Evidence(
        games={pid: points for pid, (points, _) in games.items()},
        positions={pid: position for pid, (_, position) in games.items()},
    )


STEADY = (10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0)
STREAKY = (2.0, 2.0, 2.0, 34.0, 2.0, 2.0, 2.0, 34.0)


def test_a_range_is_his_own_games_rescaled_to_this_weeks_projection() -> None:
    """Centred on the projection, which already reads the matchup; shaped by his history."""
    spread = spreads(_evidence(rb1=(STREAKY, "RB")))

    week = outcomes(_proj("rb1", "Streaky", "RB", 20.0), spread)

    assert sum(week.samples) / len(week.samples) == pytest.approx(20.0)
    assert min(week.samples) < 5 < 50 < max(week.samples)


def test_a_steady_player_keeps_a_narrow_range_and_a_streaky_one_a_wide_one() -> None:
    spread = spreads(_evidence(wr1=(STEADY, "WR"), wr2=(STREAKY, "WR")))

    steady = outcomes(_proj("wr1", "Steady", "WR", 10.0), spread)
    streaky = outcomes(_proj("wr2", "Streaky", "WR", 10.0), spread)

    # By spread, not range: both borrow their position's tails in small doses.
    assert pstdev(steady.samples) < pstdev(streaky.samples)


def test_a_boom_game_is_trimmed_to_the_cap_before_the_range_is_recentred() -> None:
    """A backup's one big week, lent to a star, reads as fiction — but trimming it
    must not drag the range's centre below the projection."""
    spread = spreads(_evidence(rb1=((6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 100.0), "RB")))

    ratios = spread.own["rb1"]
    uncapped = 100.0 / (sum((6.0,) * 7 + (100.0,)) / 8)
    assert sum(ratios) / len(ratios) == pytest.approx(1.0)
    assert max(ratios) < uncapped


def test_a_player_averaging_almost_nothing_shapes_no_range() -> None:
    spread = spreads(_evidence(rb9=((0.0, 1.0, 2.0), "RB")))

    assert "rb9" not in spread.own and not spread.pool


def test_a_player_with_no_games_borrows_his_positions_range() -> None:
    spread = spreads(_evidence(wr1=(STREAKY, "WR")))

    rookie = outcomes(_proj("new", "Rookie", "WR", 12.0), spread)

    assert len(set(rookie.samples)) > 1
    assert sum(rookie.samples) / len(rookie.samples) == pytest.approx(12.0)


def test_a_thin_history_leans_on_the_position_and_a_long_one_on_himself() -> None:
    pool = Spreads(own={"one": (3.0,), "many": (3.0,) * 12}, pool={"WR": (1.0,) * 40})

    def own_share(pid: str) -> float:
        samples = outcomes(_proj(pid, pid, "WR", 10.0), pool).samples
        return sum(1 for s in samples if s == 30.0) / len(samples)

    assert own_share("one") < 0.5 < own_share("many")


def test_with_nothing_played_the_range_is_the_projection() -> None:
    week = outcomes(_proj("x", "X", "RB", 9.5), spreads(Evidence()))

    assert week.samples == (9.5,)


@pytest.mark.parametrize(
    ("status", "chance"), [("Out", 0.0), ("IR", 0.0), ("Doubtful", 0.25), ("Questionable", 0.8), ("", 1.0)]
)
def test_whether_he_plays_follows_his_designation(status: str, chance: float) -> None:
    player = replace(_proj("x", "X", "RB", 10.0), injury_status=status)

    assert outcomes(player, spreads(Evidence())).plays == chance


def test_a_player_with_no_game_this_week_does_not_play() -> None:
    assert outcomes(_proj("x", "X", "RB", 10.0, opp=""), spreads(Evidence())).plays == 0.0


def test_a_finished_game_fixes_his_score() -> None:
    week = outcomes(_proj("x", "X", "RB", 10.0), spreads(Evidence()), status="complete", scored=23.4)

    assert (week.floor, week.remaining, week.samples) == (23.4, 0.0, ())


def test_a_game_under_way_keeps_what_he_has_and_adds_what_is_left() -> None:
    """Under way settles that he is playing, whatever his designation said."""
    player = replace(_proj("x", "X", "RB", 10.0), injury_status="Questionable")

    week = outcomes(player, spreads(Evidence()), status="in_game", scored=8.0)

    assert (week.floor, week.remaining, week.plays) == (8.0, UNDER_WAY, 1.0)


def test_a_game_under_way_has_as_much_left_as_its_clock_says() -> None:
    week = outcomes(_proj("x", "X", "RB", 10.0), spreads(Evidence()), status="in_game", scored=8.0, left=0.2)

    assert week.remaining == 0.2


def test_every_ruled_out_designation_means_he_does_not_play() -> None:
    assert all(PLAYS[s] == 0.0 for s in ("OUT", "IR", "PUP", "SUS", "NA", "DNR"))


# ── last season, for the shape of a position ────────────────────────────


def test_last_season_shapes_a_positions_range_but_not_a_players_own() -> None:
    """Position spreads barely move year to year; a player's role can."""
    this = _evidence(rb1=((12.0,), "RB"))
    last = _evidence(rb1=(STREAKY, "RB"), rb2=(STREAKY, "RB"))

    spread = spreads(this, pool_from=last)

    assert spread.own["rb1"] == (1.0,)
    assert len(set(spread.pool["RB"])) > 1


def test_without_last_season_the_opening_weeks_have_no_pool() -> None:
    """Why last season is read at all: nobody has the games yet."""
    assert spreads(_evidence(rb1=((12.0,), "RB"))).pool == {}


def test_a_quarterback_and_his_receivers_share_a_passing_game_and_his_backs_do_not() -> None:
    spread = spreads(Evidence())
    qb, wr, rb = (
        outcomes(_proj(pid, pid, position, 10.0, team="KC"), spread)
        for pid, position in (("qb", "QB"), ("wr", "WR"), ("rb", "RB"))
    )

    assert qb.group == wr.group != ""
    assert rb.group == ""
