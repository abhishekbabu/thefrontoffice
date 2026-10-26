"""Tests for the Yahoo provider's trade context."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import FakeNBA, FakeSleeperProjections, FakeYahoo, capture_logs, make_player

from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import TradeProposal

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
YAHOO_LOGGER = YahooNBAProvider.__module__


def _provider(yahoo: FakeYahoo) -> YahooNBAProvider:
    return YahooNBAProvider(
        SimpleNamespace(id="1", name="One"),
        nba=FakeNBA(),
        yahoo_for=lambda _: yahoo,
        sleeper=FakeSleeperProjections(),
        max_weekly_adds=3,
    )


def _resolve(yahoo: FakeYahoo, names: list[str]) -> Any:
    """Resolve one side through the shared trade-resolution policy."""
    from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides

    giving, _ = resolve_sides(TradeProposal(giving=names, receiving=[]), _provider(yahoo)._find_player)
    return giving


def _yahoo_with(*names: str) -> FakeYahoo:
    return FakeYahoo(search_results={n: [make_player(n)] for n in names})


# ── player resolution ───────────────────────────────────────────────────


def test_an_exact_match_resolves() -> None:
    yahoo = _yahoo_with("LeBron James")
    assert len(_resolve(yahoo, ["LeBron James"])) == 1
    assert yahoo.searches == ["LeBron James"]


def test_the_surname_is_tried_when_the_full_name_misses() -> None:
    """'Lebron James' (wrong casing) misses, but 'James' still finds him."""
    yahoo = FakeYahoo(search_results={"James": [make_player("LeBron James")]})
    assert len(_resolve(yahoo, ["Lebron James"])) == 1
    assert yahoo.searches == ["Lebron James", "James"]


def test_an_unresolved_name_raises_rather_than_being_dropped() -> None:
    """Dropping one would evaluate a different trade than was described."""
    yahoo = _yahoo_with("LeBron James")
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _resolve(yahoo, ["LeBron James", "Notarealplayer"])
    assert excinfo.value.names == ["Notarealplayer"]


def test_every_unresolved_name_is_reported_at_once() -> None:
    """Across both sides, so one message covers the whole trade."""
    from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides

    proposal = TradeProposal(giving=["Ghost One"], receiving=["Ghost Two"])
    with pytest.raises(PlayerNotFoundError) as excinfo:
        resolve_sides(proposal, _provider(FakeYahoo())._find_player)
    assert excinfo.value.names == ["Ghost One", "Ghost Two"]


def test_surrounding_whitespace_is_stripped() -> None:
    yahoo = _yahoo_with("LeBron James")
    assert len(_resolve(yahoo, ["  LeBron James  "])) == 1


def test_an_ambiguous_match_takes_the_first_and_warns() -> None:
    yahoo = FakeYahoo(search_results={"Williams": [make_player("Jalen Williams"), make_player("Jaylen Williams")]})
    with capture_logs(YAHOO_LOGGER, logging.WARNING) as logs:
        resolved = _resolve(yahoo, ["Williams"])
    assert len(resolved) == 1
    assert "2 matches" in logs.at(logging.WARNING)[0]


# ── trade context ───────────────────────────────────────────────────────


def _context(yahoo: FakeYahoo | None = None, **kwargs: Any) -> Any:
    y = yahoo or _yahoo_with("LeBron James", "Jayson Tatum")
    proposal = TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
    return _provider(y).build_trade_context("", proposal)


def test_both_sides_and_the_roster_reach_the_prompt() -> None:
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    yahoo.roster = [make_player("Existing Starter")]
    prompt = _context(yahoo).prompt
    assert "LeBron James" in prompt
    assert "Jayson Tatum" in prompt
    assert "Existing Starter" in prompt  # the roster-awareness rule needs this


def test_the_matchup_is_carried_as_the_situation() -> None:
    assert "CURRENT MATCHUP" in _context().situation


def test_a_roster_failure_degrades_without_losing_the_evaluation() -> None:
    """Roster context is enrichment; losing it must not lose the answer."""

    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")

    def _explode() -> Any:
        raise RuntimeError("yahoo hiccup")

    team = yahoo.get_user_team()
    team.players = _explode
    yahoo.get_user_team = lambda: team

    context = _provider(yahoo).build_trade_context(
        "", TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
    )
    assert "Roster data unavailable" in context.prompt
