"""Tests for football in its own terms: `competitions/nfl/model.py`."""

from thefrontoffice.adapters.outbound.competitions.nfl import model
from thefrontoffice.adapters.outbound.platforms.sleeper import types as sleeper
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame, SleeperRoster


def test_the_club_of_nobody_is_the_one_sleeper_files_him_under() -> None:
    """The platform cannot import the competition, so the two are kept in step
    here: a free agent filed under any other club would read as signed."""
    assert model.FREE_AGENT == sleeper.FREE_AGENT


def test_a_player_in_reserve_or_taxi_takes_no_spot_on_the_roster() -> None:
    team = SleeperRoster(roster_id=1, owner_id="me", player_ids=["a", "b", "c"], starter_ids=["a"], reserve_ids=["b"])

    assert model.active(team) == ["a", "c"]


def test_each_club_finds_its_game_from_either_side_and_a_club_on_bye_none() -> None:
    game = ScheduledGame(week=4, date="2026-10-04", home="MIA", away="NYJ")

    index = model.by_club([game])

    assert index["MIA"] is game and index["NYJ"] is game
    assert "BUF" not in index
