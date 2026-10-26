"""Tests for the Yahoo provider's trade context."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from support.logs import capture_logs
from support.nba import FakeYahoo, make_player, nba_provider

from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import TradeProposal

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
YAHOO_LOGGER = YahooNBAProvider.__module__


def _provider(yahoo: FakeYahoo) -> YahooNBAProvider:
    return nba_provider(yahoo, league=SimpleNamespace(id="1", name="One"))


def _resolve(yahoo: FakeYahoo, names: list[str]) -> Any:
    """Resolve one side through the shared trade-resolution policy."""
    from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides

    giving, _ = resolve_sides(TradeProposal(giving=names, receiving=[]), _provider(yahoo)._find_player)
    return giving


def _yahoo_with(*names: str) -> FakeYahoo:
    return FakeYahoo(search_results={n: [make_player(n)] for n in names})


# ── player resolution ───────────────────────────────────────────────────


def _names(players: list[Any]) -> list[str]:
    return [p.name.full for p in players]


def test_an_exact_match_resolves() -> None:
    assert _names(_resolve(_yahoo_with("LeBron James"), ["LeBron James"])) == ["LeBron James"]


def test_the_surname_is_tried_when_the_full_name_misses() -> None:
    """'Lebron James' (wrong casing) misses, but 'James' still finds him."""
    yahoo = FakeYahoo(search_results={"James": [make_player("LeBron James")]})
    assert _names(_resolve(yahoo, ["Lebron James"])) == ["LeBron James"]


def test_an_unresolved_name_raises_rather_than_being_dropped() -> None:
    """Dropping one would evaluate a different trade than was described."""
    yahoo = _yahoo_with("LeBron James")
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _resolve(yahoo, ["LeBron James", "Notarealplayer"])
    assert excinfo.value.names == ["Notarealplayer"]


def test_an_ambiguous_match_takes_the_first_and_warns() -> None:
    yahoo = FakeYahoo(search_results={"Williams": [make_player("Jalen Williams"), make_player("Jaylen Williams")]})
    with capture_logs(YAHOO_LOGGER, logging.WARNING) as logs:
        resolved = _resolve(yahoo, ["Williams"])
    assert _names(resolved) == ["Jalen Williams"]
    assert len(logs.at(logging.WARNING)) == 1


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
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    assert _context(yahoo).situation == yahoo.get_matchup(yahoo.get_user_team()).context


def test_a_roster_failure_degrades_without_losing_the_evaluation() -> None:
    """Roster context is enrichment; losing it must not lose the answer."""
    yahoo = FakeYahoo(
        search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")},
        roster=[make_player("Existing Starter")],
        roster_error=RuntimeError("yahoo hiccup"),
    )

    prompt = _context(yahoo).prompt

    assert "LeBron James" in prompt
    assert "Jayson Tatum" in prompt
    assert "Existing Starter" not in prompt
