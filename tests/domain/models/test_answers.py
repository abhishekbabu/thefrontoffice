"""Tests for the models of what the model is asked and answers."""

from thefrontoffice.domain.models import TradeProposal


def test_both_sides_populated_is_valid() -> None:
    assert TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"]).is_valid


def test_one_sided_proposals_are_invalid() -> None:
    assert not TradeProposal(giving=["LeBron James"], receiving=[]).is_valid
    assert not TradeProposal(giving=[], receiving=["Jayson Tatum"]).is_valid


def test_empty_proposal_is_invalid() -> None:
    """What a parse that found neither side yields, so it must be falsy."""
    assert not TradeProposal().is_valid
