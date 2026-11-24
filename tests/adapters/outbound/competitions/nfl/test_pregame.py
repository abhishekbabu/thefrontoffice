"""Tests for keeping each player's projection as first read before his game: `nfl/pregame.py`."""

from dataclasses import replace

from support.nfl import proj
from support.stores import FakeProjectionLog

from thefrontoffice.adapters.outbound.competitions.nfl.pregame import kept, record

WARREN = proj("te", "Tyler Warren", "TE", 10.4, team="IND", opp="NYG")
BARNER = proj("fa", "AJ Barner", "TE", 7.0, team="SEA", opp="ARI")


def test_a_players_projection_is_kept_only_while_his_game_has_yet_to_start() -> None:
    log = FakeProjectionLog()

    record(log, "2026", 12, {"te": WARREN, "fa": BARNER}, started={"SEA"})

    assert log.week("2026", 12) == {"te": 10.4}


def test_the_first_read_before_kickoff_is_never_replaced() -> None:
    """Sleeper cut him to 6 an hour before kickoff; the 10.4 read the day before is what he was expected to do."""
    log = FakeProjectionLog()
    record(log, "2026", 12, {"te": WARREN}, started=set())

    record(log, "2026", 12, {"te": replace(WARREN, points=6.0), "fa": BARNER}, started=set())

    assert log.week("2026", 12) == {"te": 10.4, "fa": 7.0}


def test_only_weeks_with_anything_kept_are_read_back() -> None:
    log = FakeProjectionLog({("2026", 11): {"te": 10.75}})

    assert kept(log, "2026", [10, 11]) == {11: {"te": 10.75}}
