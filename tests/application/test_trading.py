"""Tests for the generic trade pipeline.

The engine knows nothing about a platform: it parses, asks a provider to price
the trade, and structures the answer.
"""

from typing import Any

import pytest
from support.ai import FakeAI, FakeChat
from support.reports import MOCK_NBA_VERDICT

from thefrontoffice.application.formats import TradeAnswer, TradeSides
from thefrontoffice.application.trading import TradeEngine
from thefrontoffice.domain.errors import AIQuotaError, AIResponseError, PlayerNotFoundError, TradeParseError
from thefrontoffice.domain.models import CompetitionContext, TradeProposal, TradeVerdict


class FakeTradeProvider:
    sport = "nba"
    label = "NBA (Yahoo)"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, TradeProposal]] = []

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        self.calls.append((league_id, proposal))
        if self.error:
            raise self.error
        # The prompt names what it was built from, so a test can see the model is
        # asked about this league's trade and not some other one.
        prompt = f"{league_id}: {', '.join(proposal.giving)} for {', '.join(proposal.receiving)}"
        return CompetitionContext(prompt=prompt, situation="matchup")


def _engine(provider: Any = None, ai: Any = None) -> TradeEngine:
    return TradeEngine(provider or FakeTradeProvider(), ai=ai or FakeAI())


def test_a_verdict_and_an_open_chat_are_returned() -> None:
    ai = FakeAI()
    verdict, chat = _engine(ai=ai).evaluate("L1", "Give LeBron, Get Tatum")
    assert isinstance(verdict, TradeVerdict)
    assert verdict == MOCK_NBA_VERDICT
    assert chat is ai.chat


def test_search_is_enabled_for_live_news() -> None:
    """Injury and standings news is most of the value in a trade call."""
    ai = FakeAI()
    _engine(ai=ai).evaluate("L1", "x")
    assert ai.search_enabled is True


def test_the_prose_is_structured_in_a_second_pass() -> None:
    """A response schema cannot accompany a tool, so prose is converted after."""
    ai = FakeAI()
    _engine(ai=ai).evaluate("L1", "x")
    assert ("[FAKE] follow-up answer", TradeAnswer) in [(text, schema) for text, schema, _ in ai.structured]


def test_the_trade_is_parsed_into_its_two_sides_by_the_parsing_pass() -> None:
    """Parsing is the fast model's job, held to a schema rather than read as JSON by hand."""
    ai = FakeAI()
    _engine(ai=ai).evaluate("L1", "Give LeBron, Get Tatum")
    assert ("Give LeBron, Get Tatum", TradeSides) == ai.structured[0][:2]


def test_an_unparseable_trade_raises_before_the_provider_is_asked() -> None:
    provider = FakeTradeProvider()
    with pytest.raises(TradeParseError):
        _engine(provider, FakeAI(proposal=TradeProposal())).evaluate("L1", "gibberish")
    assert provider.calls == []


def test_the_model_is_asked_about_this_leagues_parsed_trade() -> None:
    ai = FakeAI(proposal=TradeProposal(giving=["A"], receiving=["B"]))
    _engine(ai=ai).evaluate("L7", "x")
    assert ai.chat.sent == ["L7: A for B"]


def test_a_provider_failure_propagates_as_a_domain_error() -> None:
    with pytest.raises(PlayerNotFoundError):
        _engine(FakeTradeProvider(error=PlayerNotFoundError(["Ghost"]))).evaluate("L1", "x")


def test_an_empty_model_response_raises() -> None:
    with pytest.raises(AIResponseError):
        _engine(ai=FakeAI(chat=FakeChat(reply=""))).evaluate("L1", "x")


def test_a_model_failure_reaches_the_caller_as_the_domain_error_it_was() -> None:
    """A chat's failures are already the model's domain errors; a spent quota stays one."""
    with pytest.raises(AIQuotaError):
        _engine(ai=FakeAI(chat=FakeChat(error=AIQuotaError("Gemini")))).evaluate("L1", "x")
