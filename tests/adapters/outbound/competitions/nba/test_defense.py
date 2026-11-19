"""Tests for what each NBA club gives up to each position: `nba/defense.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.nba.defense import allowed
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta


def _log(pid: str, day: str, opponent: str, **stats: float) -> NBAGameLog:
    return NBAGameLog(player_id=pid, date=day, opponent=opponent, stats=stats)


SCORES = BoxScores(
    logs={
        "pg1": [_log("pg1", "2026-11-01", "BOS", pts=30, ast=10), _log("pg1", "2026-11-03", "MIA", pts=10, ast=2)],
        "pg2": [_log("pg2", "2026-11-01", "BOS", pts=10, ast=4)],
        "c1": [_log("c1", "2026-11-03", "MIA", pts=25)],
        "nobody": [_log("nobody", "2026-11-03", "MIA", pts=50)],
    },
    players={
        "pg1": PlayerMeta(player_id="pg1", name="One", position="PG"),
        "pg2": PlayerMeta(player_id="pg2", name="Two", position="PG"),
        "c1": PlayerMeta(player_id="c1", name="Big", position="C"),
        "nobody": PlayerMeta(player_id="nobody", name="Coach", position=""),
    },
)


def test_points_allowed_to_a_position_sum_its_players_per_game_the_club_played() -> None:
    found = allowed(SCORES)

    boston, miami = found["BOS", "PG"], found["MIA", "PG"]
    assert (boston.allowed, boston.rank, boston.unit) == (pytest.approx(40.0), 1, "pts")
    assert (miami.allowed, miami.rank) == (pytest.approx(10.0), 2)
    assert found["BOS", "C"].allowed == 0.0


def test_a_player_without_one_of_the_five_positions_counts_for_nobody() -> None:
    assert {position for _, position in allowed(SCORES)} == {"PG", "C"}


def test_a_points_league_reads_what_a_club_allows_in_its_fantasy_points() -> None:
    found = allowed(SCORES, {"12": 1.0, "16": 2.0})

    assert (found["BOS", "PG"].allowed, found["BOS", "PG"].unit) == (pytest.approx(68.0), "fpts")
