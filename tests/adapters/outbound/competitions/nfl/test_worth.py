"""Tests for what a player is worth to a lineup: `nfl/worth.py`, its rest-of-season reading.

The rest is read through the to-do list in `test_actions.py`; this is the case only a hand-built week shows exactly.
"""

from dataclasses import replace

import pytest
from support.nfl import SLEEPER_USER_ID, game_line, proj, week_of

from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import (
    CALIBRATION_MOST,
    calibration,
    projected_ahead,
    rest_of_season,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta, SleeperLeague, SleeperRoster

LEAGUE = SleeperLeague(
    league_id="L1", name="Small", season="2026", total_rosters=2, scoring_format="pts_ppr", roster_positions=["BN"]
)
BACK = proj("rb", "Returning Back", "RB", 7.0, team="WAS", opp="SEA")


def _week(weeks: dict[int, float], ahead: float) -> Week:
    lines = [
        game_line("rb", week, position="RB", team="WAS", off_snp=40.0, tm_off_snp=100.0, pts_ppr=points)
        for week, points in weeks.items()
    ]
    roster = SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["rb"], starter_ids=[])
    meta = {"rb": PlayerMeta(player_id="rb", name=BACK.name, position="RB", team="WAS")}
    state = week_of(LEAGUE, roster, [BACK], meta, lines=lines)
    return replace(state, ahead={"rb": ahead})


def test_a_player_back_from_an_absence_is_read_on_his_games_since() -> None:
    """8 a game before he went out, 16 in his game back, 6 projected ahead: (16 + 6) / 2, not (9.33 + 6) / 2."""
    state = _week({1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 8.0, 11: 16.0}, ahead=6.0)

    assert rest_of_season(state, BACK) == pytest.approx((16.0 + 6.0) / 2)


def test_a_player_with_no_absence_is_read_on_his_season() -> None:
    state = _week(dict.fromkeys(range(1, 7), 8.0), ahead=6.0)

    assert rest_of_season(state, BACK) == pytest.approx((8.0 + 6.0) / 2)


def _scored(points: list[float], projected: float, ahead: float = 10.0) -> Week:
    """Weeks 1 on at these points, each projected `projected`, and `ahead` a game projected for the weeks left."""
    state = _week(dict(enumerate(points, start=1)), ahead=ahead)
    return replace(state, past={week: {"rb": projected} for week in range(1, len(points) + 1)})


def test_beating_his_projections_lifts_what_he_is_projected_ahead_by_how_settled_the_record_is() -> None:
    """Eight games at 12 on projections of 10: 20% over, eight games counting 8 / (8 + 4) of it."""
    assert calibration(_scored([12.0] * 8, 10.0), "rb") == pytest.approx(1 + 0.2 * 8 / 12)


def test_his_record_against_projections_moves_them_a_quarter_at_most() -> None:
    assert calibration(_scored([30.0] * 8, 10.0), "rb") == pytest.approx(1 + CALIBRATION_MOST)
    assert calibration(_scored([0.5] * 8, 10.0), "rb") == pytest.approx(1 - CALIBRATION_MOST)


def test_without_stored_projections_his_record_says_nothing() -> None:
    assert calibration(_week({1: 12.0, 2: 12.0}, ahead=10.0), "rb") == 1.0


def test_projected_ahead_is_sleepers_figure_read_against_his_record() -> None:
    state = _scored([12.0] * 8, 10.0, ahead=9.0)

    assert projected_ahead(state, BACK) == pytest.approx(9.0 * calibration(state, "rb"))
    assert projected_ahead(replace(state, ahead={}), BACK) is None
