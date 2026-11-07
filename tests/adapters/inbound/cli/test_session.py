"""Tests for a CLI session: which competitions it runs over, and building each provider once."""

import pytest
from support.wiring import FakeCompetition, entry, wiring

from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.domain.errors import NotConfiguredError


def test_a_provider_is_built_once_per_session() -> None:
    """Building the NBA provider opens an OAuth flow; twice would be twice."""
    built: list[int] = []
    nfl = entry(FakeCompetition(), built=built)
    session = Session(wiring(nfl))

    session.provider(nfl)
    session.provider(nfl)

    assert built == [1]


def test_a_session_runs_over_the_configured_competitions_only() -> None:
    nfl = entry(FakeCompetition())
    nba = entry(FakeCompetition(), competition="nba", platform="yahoo", configured=False)

    assert Session(wiring(nfl, nba)).entries == [nfl]


def test_an_unconfigured_competition_is_never_built() -> None:
    built: list[int] = []
    nba = entry(FakeCompetition(), configured=False, requires="YAHOO_CLIENT_ID", built=built)

    with pytest.raises(NotConfiguredError, match="YAHOO_CLIENT_ID"):
        Session(wiring(nba)).provider(nba)
    assert built == []
