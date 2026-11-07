"""Tests for the Yahoo provider's trade context."""

import logging

import pytest
from support.logs import capture_logs
from support.nba import FakeYahoo, make_player, nba_provider

from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooUnavailableError
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import CompetitionContext, TradeProposal

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
YAHOO_LOGGER = YahooNBAProvider.__module__


def _giving(yahoo: FakeYahoo, *names: str) -> str:
    """The prompt for giving `names` away for nothing, which names whom each resolved to."""
    return nba_provider(yahoo).build_trade_context("", TradeProposal(giving=list(names), receiving=[])).prompt


def _yahoo_with(*names: str) -> FakeYahoo:
    return FakeYahoo(search_results={n: [make_player(n)] for n in names})


# ── player resolution ───────────────────────────────────────────────────


def test_an_exact_match_resolves() -> None:
    assert "LeBron James" in _giving(_yahoo_with("LeBron James"), "LeBron James")


def test_the_surname_is_tried_when_the_full_name_misses() -> None:
    """'Lebron James' (wrong casing) misses, but 'James' still finds him."""
    yahoo = FakeYahoo(search_results={"James": [make_player("LeBron James")]})
    assert "LeBron James" in _giving(yahoo, "Lebron James")


def test_the_exact_name_wins_among_several_matches() -> None:
    """Yahoo's search matches substrings, so a name can bring others with it."""
    yahoo = FakeYahoo(
        search_results={"James": [make_player("Jalen James"), make_player("LeBron James"), make_player("Mike James")]}
    )
    prompt = _giving(yahoo, "Lebron James")
    assert "LeBron James" in prompt
    assert "Jalen James" not in prompt


def test_an_ambiguous_surname_resolves_to_nobody_rather_than_the_first() -> None:
    """Pricing whichever Williams Yahoo listed first would evaluate a trade
    nobody proposed."""
    yahoo = FakeYahoo(search_results={"Williams": [make_player("Jalen Williams"), make_player("Jaylen Williams")]})
    with capture_logs(YAHOO_LOGGER, logging.WARNING) as logs, pytest.raises(PlayerNotFoundError) as excinfo:
        _giving(yahoo, "Williams")
    assert excinfo.value.names == ["Williams"]
    assert len(logs.at(logging.WARNING)) == 1


# ── trade context ───────────────────────────────────────────────────────


def _context(yahoo: FakeYahoo) -> CompetitionContext:
    proposal = TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
    return nba_provider(yahoo).build_trade_context("", proposal)


def test_both_sides_and_the_roster_reach_the_prompt() -> None:
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    yahoo.roster_players = [make_player("Existing Starter")]
    prompt = _context(yahoo).prompt
    assert "LeBron James" in prompt
    assert "Jayson Tatum" in prompt
    assert "Existing Starter" in prompt  # the roster-awareness rule needs this


def test_the_matchup_is_carried_as_the_situation() -> None:
    situation = _context(_yahoo_with("LeBron James", "Jayson Tatum")).situation
    assert "Their Team" in situation
    assert "BLK: 12 vs 17" in situation


def test_the_roster_rides_along_for_the_follow_up_briefing() -> None:
    """A follow-up is seeded from the roster lines, not the generation prompt."""
    yahoo = FakeYahoo(
        search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")},
        roster=[make_player("Existing Starter")],
    )

    assert list(_context(yahoo).roster_lines) == ["Existing Starter"]


def test_a_roster_failure_fails_the_evaluation_rather_than_judging_without_it() -> None:
    """A trade is judged against the roster it changes; without it the answer is to a different question."""
    yahoo = FakeYahoo(
        search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")},
        roster=[make_player("Existing Starter")],
        roster_error=YahooUnavailableError("yahoo hiccup"),
    )

    with pytest.raises(YahooUnavailableError):
        _context(yahoo)
