"""Tests for pricing a player by his own games as well as his projection: `nfl/form.py`.

The evidence is written by hand, so every price below can be checked with a pencil.
"""

import pytest
from support.nfl import proj

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence, Role, Trend
from thefrontoffice.adapters.outbound.competitions.nfl.form import bent, forms, said
from thefrontoffice.adapters.outbound.platforms.sleeper.types import WeeklyProjection

WEEKS = [8, 9]


def _projected(
    pid: str, points: float, position: str = "WR", weeks: list[int] = WEEKS
) -> dict[int, dict[str, WeeklyProjection]]:
    return {week: {pid: proj(pid, pid, position, points)} for week in weeks}


def _played(pid: str, *games: float, recent: float | None = None, trend: Trend | None = None) -> Evidence:
    role = Role(position="WR", games=min(3, len(games)), points=recent if recent is not None else games[-1])
    return Evidence(roles={pid: role}, games={pid: games}, positions={pid: "WR"}, trends={pid: trend} if trend else {})


def test_a_steady_role_is_priced_halfway_to_his_recent_and_season_scoring() -> None:
    """12 recent and 10 for the season is a rate of 11.2; halfway from a projection of 10 is 10.6."""
    found = forms(_played("wr", 10, 8, 12, recent=12), _projected("wr", 10.0), WEEKS)

    assert found["wr"].factor == pytest.approx(1.06)
    assert found["wr"].projected == pytest.approx(10.0)


def test_a_changed_role_is_priced_on_the_games_since_it_changed() -> None:
    """The weeks before it are another player's: 18 and 20 since, not the 4s before them."""
    trend = Trend(measure="snaps", before=0.3, now=0.8, week=9, rise=2.5, games=2)

    found = forms(_played("rb", 4, 4, 4, 18, 20, recent=14, trend=trend), _projected("rb", 12.0), WEEKS)

    # A rate of 19 over a projection of 12, pulled halfway: 15.5, under the 30% bound.
    assert found["rb"].factor == pytest.approx(15.5 / 12)
    assert "snaps 30→80%" in found["rb"].reason and "2 games since" in found["rb"].reason


def test_one_big_game_cannot_move_his_price_more_than_thirty_percent() -> None:
    trend = Trend(measure="snaps", before=0.2, now=0.9, week=9, rise=3.5, games=1)

    found = forms(_played("rb", 2, 2, 40, trend=trend), _projected("rb", 8.0), WEEKS)

    assert found["rb"].factor == pytest.approx(1.3)


def test_a_role_that_dried_up_is_priced_down() -> None:
    found = forms(_played("wr", 18, 6, 6, 6, recent=6), _projected("wr", 17.0), WEEKS)

    assert found["wr"].factor < 1


def test_a_player_with_one_game_and_no_changed_role_is_left_at_his_projection() -> None:
    assert forms(_played("wr", 25), _projected("wr", 10.0), WEEKS) == {}


def test_a_kicker_is_left_at_his_projection() -> None:
    """His week turns on the opponent, which the projection already reads."""
    evidence = Evidence(roles={"k": Role(position="K", games=3, points=15)}, games={"k": (15, 15, 15)})

    assert forms(evidence, _projected("k", 8.0, position="K"), WEEKS) == {}


def test_a_bye_is_not_read_as_a_week_he_scores_nothing() -> None:
    """His projection a week is across the weeks he plays, and his bye stays at nothing once bent."""
    projections = {8: {"wr": proj("wr", "wr", "WR", 10.0)}, 9: {"wr": proj("wr", "wr", "WR", 0.0)}}

    found = forms(_played("wr", 12, 12, 12, recent=12), projections, WEEKS)
    priced = bent(projections, found)

    assert found["wr"].projected == pytest.approx(10.0)
    assert priced[8]["wr"].points == pytest.approx(11.0)
    assert priced[9]["wr"].points == 0.0


def test_only_a_price_moved_enough_to_matter_is_said_beside_a_trade() -> None:
    found = forms(_played("wr", 10, 10, 10.4, recent=10.4), _projected("wr", 10.0), WEEKS)
    found |= forms(_played("rb", 20, 20, 20, recent=20), _projected("rb", 10.0), WEEKS)

    [line] = said(found, ["wr", "rb"], {"rb": "Lead Back"})

    assert line.label == "Lead Back"
    assert "projected 10.0" in line.value and "priced 13.0" in line.value
