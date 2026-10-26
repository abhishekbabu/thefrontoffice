"""Live checks against the Fantasy Premier League API.

Deselected by default. These exist because the shapes this adapter reads are
not documented anywhere the game guarantees: FPL reworks its payloads over the
summer, and the failure mode is a report built from silently empty data rather
than an error. Run with `just test-integration` before each season.
"""

from pathlib import Path

import pytest

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient
from thefrontoffice.adapters.outbound.platforms.fpl.types import POSITIONS, SQUAD_SIZE

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path) -> FPLClient:
    """A client whose cache is thrown away, so each run really hits the API."""
    return FPLClient(cache=JsonDiskCache(tmp_path / "cache"))


def test_the_bootstrap_still_carries_a_full_league(client: FPLClient) -> None:
    assert len(client.get_teams()) == 20
    assert len(client.get_gameweeks()) == 38


def test_players_still_carry_the_projection_the_report_rests_on(client: FPLClient) -> None:
    """`ep_next` is the forward-looking number; without it there is no report."""
    players = client.get_players()
    assert len(players) > 400
    assert sum(p.expected_points > 0 for p in players.values()) > 100


def test_players_still_carry_expected_goals(client: FPLClient) -> None:
    """The reason FPL needs no second stats provider the way the NBA path does."""
    players = client.get_players()
    assert sum(p.expected_goal_involvements > 0 for p in players.values()) > 20


def test_every_player_resolves_to_a_position_and_a_club(client: FPLClient) -> None:
    for player in client.get_players().values():
        assert player.position in POSITIONS.values()
        assert player.team != "???"


def test_the_upcoming_gameweek_has_a_future_deadline(client: FPLClient) -> None:
    assert client.upcoming_gameweek().id in range(1, 39)


def test_a_real_squad_reads_back_as_fifteen(client: FPLClient) -> None:
    """Entry 1 is the game's own oldest account and is always present."""
    upcoming = client.upcoming_gameweek().id
    if upcoming <= 1:
        pytest.skip("the season has not started, so no picks are published")
    squad = client.get_squad(1, upcoming - 1)
    assert len(squad.picks) == SQUAD_SIZE
    assert sum(pick.is_starting for pick in squad.picks) == 11


def test_fixtures_resolve_to_known_clubs(client: FPLClient) -> None:
    clubs = set(client.get_teams().values())
    for fixture in client.get_fixtures(client.upcoming_gameweek().id):
        assert {fixture.home, fixture.away} <= clubs
