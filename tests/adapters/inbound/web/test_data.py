"""Tests for the UI data layer."""

import pytest

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.domain.errors import LeagueNotFoundError

# ── season rollover ─────────────────────────────────────────────────────


# ── provider construction ───────────────────────────────────────────────


def test_unknown_competition_raises() -> None:
    with pytest.raises(LeagueNotFoundError, match="cricket"):
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
