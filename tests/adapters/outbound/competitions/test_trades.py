"""Tests for the shared trade policy: resolving the players named, and what could be offered for one."""

import pytest

from thefrontoffice.adapters.outbound.competitions.trades import offers, resolve_sides
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


def test_every_unresolved_name_on_either_side_raises_together() -> None:
    """Dropping one would evaluate a different trade than was described; one message to fix, not one per re-run."""
    with pytest.raises(PlayerNotFoundError) as excinfo:
        resolve_sides(TradeProposal(giving=["Ghost", "Star QB"], receiving=["Also Missing"]), _resolve_one)
    assert excinfo.value.names == ["Ghost", "Also Missing"]


WORTH = {"star": 100.0, "good": 85.0, "half": 50.0, "other half": 40.0, "scrap": 5.0, "nothing": 0.0}


def test_one_player_worth_near_what_is_asked_is_offered_alone() -> None:
    assert ("good",) in offers(list(WORTH), WORTH.__getitem__, 100.0)


def test_two_are_offered_only_where_neither_alone_is_enough() -> None:
    """A pair with a player who would do alone is that player thrown away."""
    offered = offers(list(WORTH), WORTH.__getitem__, 100.0)

    assert ("half", "other half") in offered
    assert not any(len(o) == 2 and ("star" in o or "good" in o) for o in offered)


def test_nobody_worth_nothing_is_offered() -> None:
    assert not any("nothing" in o for o in offers(list(WORTH), WORTH.__getitem__, 10.0))
