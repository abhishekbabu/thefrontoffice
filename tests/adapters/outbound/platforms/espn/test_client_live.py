"""Live checks against ESPN's public site API.

Deselected by default. The injury report's shape is undocumented, and the
failure mode is a drawer that silently never shows a return date rather than
an error. Run with `just test-integration`.
"""

from pathlib import Path

import pytest

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
from thefrontoffice.adapters.outbound.platforms.espn.types import NFL
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
