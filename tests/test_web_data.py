"""Tests for the UI data layer."""

from datetime import datetime

import pytest

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.adapters.outbound.competitions.nba.form import PACIFIC
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.domain.errors import LeagueNotFoundError

# ── season rollover ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 20, tzinfo=PACIFIC), 2026),  # opening night
        (datetime(2026, 12, 31, tzinfo=PACIFIC), 2026),
        (datetime(2027, 1, 2, tzinfo=PACIFIC), 2026),  # January still belongs to the prior season
        (datetime(2027, 4, 15, tzinfo=PACIFIC), 2026),  # playoffs
        (datetime(2026, 9, 1, tzinfo=PACIFIC), 2026),  # September boundary, inclusive
        (datetime(2026, 8, 31, tzinfo=PACIFIC), 2025),  # the day before
    ],
)
def test_nba_season_rolls_over_in_september(when: datetime, expected: int) -> None:
    """Lived in the UI layer as a bare `season_year`; it is basketball's calendar
    and belongs to the basketball provider."""
    assert YahooNBAProvider.season_year(when) == expected


# ── provider construction ───────────────────────────────────────────────


def test_unknown_competition_raises() -> None:
    with pytest.raises(LeagueNotFoundError, match="unknown competition"):
        data.build_provider("cricket")


def test_an_unconfigured_sport_names_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A football-only user picking NBA must be told what is missing, not
    dropped into an OAuth flow."""
    with pytest.raises(LeagueNotFoundError, match="YAHOO_CLIENT_ID"):
        data.build_provider("nba")


def test_a_configured_sport_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.config.settings import settings

    monkeypatch.setattr(settings, "sleeper_username", "someone")
    provider = data.build_provider("nfl")
    assert provider.competition == "nfl"


# ── situation parsing ───────────────────────────────────────────────────
