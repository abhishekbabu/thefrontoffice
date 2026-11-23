"""Tests for the registry's types: what an entry can do, read off its provider without building it."""

import pytest
from support.wiring import FakeCompetition, entry

from thefrontoffice.domain.errors import UnsupportedError
from thefrontoffice.domain.models import CompetitionContext, TradeProposal
from thefrontoffice.domain.ports import OutlookProvider, TradeProvider, WireProvider


class _Trades(FakeCompetition):
    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        raise AssertionError("not asked")


def test_asking_what_a_competition_can_do_builds_nothing() -> None:
    """A client asks before anything is chosen, and building one reads its settings and opens its caches."""
    built: list[int] = []
    trades = entry(_Trades(), built=built)

    assert (trades.can(TradeProvider), trades.can(WireProvider), trades.can(OutlookProvider)) == (True, False, False)
    assert built == []


def test_a_capability_it_lacks_is_refused_by_name_without_building() -> None:
    built: list[int] = []
    plain = entry(FakeCompetition(), label="Plain", built=built)

    with pytest.raises(UnsupportedError, match="Plain"):
        plain.open_as(WireProvider, "judging free agents")
    assert built == []


def test_a_capability_it_has_comes_back_as_that_port() -> None:
    provider = _Trades()

    assert entry(provider).open_as(TradeProvider, "trade evaluation") is provider
