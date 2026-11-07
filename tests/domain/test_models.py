"""Tests for the domain's own models."""

from thefrontoffice.domain.models import TradeProposal, Urgency, urgency_rank

# ── TradeProposal ───────────────────────────────────────────────────────


def test_both_sides_populated_is_valid() -> None:
    assert TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"]).is_valid


def test_one_sided_proposals_are_invalid() -> None:
    assert not TradeProposal(giving=["LeBron James"], receiving=[]).is_valid
    assert not TradeProposal(giving=[], receiving=["Jayson Tatum"]).is_valid


def test_empty_proposal_is_invalid() -> None:
    """What a parse that found neither side yields, so it must be falsy."""
    assert not TradeProposal().is_valid


# ── urgency ─────────────────────────────────────────────────────────────


def test_urgency_sorts_most_pressing_first() -> None:
    order: list[Urgency] = ["later", "now", "soon"]
    assert sorted(order, key=urgency_rank) == ["now", "soon", "later"]
