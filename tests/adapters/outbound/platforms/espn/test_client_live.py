"""Live checks against ESPN's public site API.

Deselected by default. The injury report's shape is undocumented, and the
failure mode is a drawer that silently never shows a return date rather than
an error. Run with `just test-integration`.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.competitions.nba.clubs import YAHOO_TO_ESPN
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA, NFL
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path) -> ESPNClient:
    """A client whose cache is thrown away, so each run really hits the API."""
    return ESPNClient(cache=JsonDiskCache(tmp_path / "cache"), retry=RetryPolicy())


def test_the_injury_report_still_carries_athlete_ids_and_return_dates(client: ESPNClient) -> None:
    hurt = [r for r in client.get_injuries(NFL) if r.status != "Active"]

    assert hurt, "an NFL injury report with nobody hurt is a broken read, not a healthy league"
    assert all(r.athlete_id.isdigit() for r in hurt)
    assert any(r.returns for r in hurt)
    assert any(r.injury for r in hurt)


def test_a_roster_names_each_player_with_an_id_his_own_injury_history_answers_to(client: ESPNClient) -> None:
    """The backfill for whoever the report has dropped: a roster's ids, then each one's own entry."""
    roster = client.get_rosters(NFL)
    assert len({a.club for a in roster}) == 32
    assert all(a.athlete_id.isdigit() and a.name for a in roster)

    # Whoever the report itself names as hurt has an entry of his own; ask after a handful of them.
    known = {a.athlete_id for a in roster}
    hurt = [r for r in client.get_injuries(NFL) if r.status != "Active" and r.athlete_id in known][:10]
    by_id = {a.athlete_id: a for a in roster}
    # A season is named for the year it kicks off; January and February still belong to the one before.
    now = datetime.now(UTC)
    season = str(now.year if now.month > 2 else now.year - 1)

    found = client.get_athlete_injuries(NFL, season, [by_id[r.athlete_id] for r in hurt])

    assert found, "nobody the report calls hurt has an entry of his own: the core API's shape has moved"
    assert all(r.status and r.updated for r in found.values())
    assert any(r.returns for r in found.values())


def test_the_nba_report_carries_return_dates_under_the_club_spellings_basketball_maps(client: ESPNClient) -> None:
    """Basketball joins by name within a club, so a club ESPN respells unmapped would match nobody on it."""
    clubs = set(client.get_teams(NBA))
    hurt = [r for r in client.get_injuries(NBA) if r.status != "Active"]

    assert len(clubs) == 30
    assert set(YAHOO_TO_ESPN.values()) <= clubs
    assert not set(YAHOO_TO_ESPN) & clubs
    assert hurt, "an NBA injury report with nobody hurt is a broken read, not a healthy league"
    assert {r.club for r in hurt} <= clubs
    assert any(r.returns for r in hurt)
