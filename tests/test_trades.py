"""Tests for the shared trade-resolution policy."""

import pytest

from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import TradeProposal

KNOWN = {"Star QB": "qb1", "Good RB": "rb1", "Waiver WR": "wr9"}


def _resolve_one(name: str) -> str | None:
    return KNOWN.get(name)


def test_both_sides_are_resolved() -> None:
    giving, receiving = resolve_sides(
        TradeProposal(giving=["Star QB"], receiving=["Good RB", "Waiver WR"]), _resolve_one
    )
    assert giving == ["qb1"]
    assert receiving == ["rb1", "wr9"]


def test_surrounding_whitespace_is_stripped() -> None:
    giving, _ = resolve_sides(TradeProposal(giving=["  Star QB  "], receiving=[]), _resolve_one)
    assert giving == ["qb1"]


def test_an_unresolved_name_raises() -> None:
    """Dropping it would evaluate a different trade than was described."""
    with pytest.raises(PlayerNotFoundError) as excinfo:
        resolve_sides(TradeProposal(giving=["Ghost"], receiving=["Good RB"]), _resolve_one)
    assert excinfo.value.names == ["Ghost"]


def test_failures_on_both_sides_are_reported_together() -> None:
    """One message to fix, rather than one per re-run."""
    with pytest.raises(PlayerNotFoundError) as excinfo:
        resolve_sides(TradeProposal(giving=["Ghost One"], receiving=["Ghost Two"]), _resolve_one)
    assert excinfo.value.names == ["Ghost One", "Ghost Two"]


def test_the_receiving_side_is_still_checked_when_giving_fails() -> None:
    with pytest.raises(PlayerNotFoundError) as excinfo:
        resolve_sides(TradeProposal(giving=["Ghost", "Star QB"], receiving=["Also Missing"]), _resolve_one)
    assert excinfo.value.names == ["Ghost", "Also Missing"]


def test_an_empty_side_resolves_to_an_empty_list() -> None:
    giving, receiving = resolve_sides(TradeProposal(giving=["Star QB"], receiving=[]), _resolve_one)
    assert giving == ["qb1"]
    assert receiving == []
