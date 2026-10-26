"""Tests for the structured report schemas."""

from thefrontoffice.domain.models import Move, TradeProposal, TradeVerdict

# Validated from dicts rather than constructors: the runtime rejection is the
# point, and a deliberately-invalid literal in a constructor call is a static
# type error the checker would (correctly) flag.
VALID_MOVE: dict[str, object] = {
    "action": "ADD",
    "player": "Test Player",
    "position": "PF",
    "team": "LAL",
    "metric": "3 games left",
    "rationale": "Rebounds at volume.",
    "replaces": "Bench Guy",
    "replaces_rationale": "No categories won.",
}

VALID_VERDICT: dict[str, object] = {
    "verdict": "ACCEPT",
    "verdict_detail": "d",
    "gains": ["REB"],
    "losses": ["AST"],
    "impact": "i",
    "schedule": "s",
    "risk": "r",
    "strategy": "st",
}


def test_every_field_carries_a_description_for_the_model() -> None:
    """Field descriptions are the schema's instructions to the model — a field
    without one gives it nothing to go on. These are what it is asked to fill."""
    from thefrontoffice.application.formats import CallAnswer, ScoutAnswer, WireAnswer
    from thefrontoffice.domain.models import TaskVerdict

    for schema in (ScoutAnswer, Move, TaskVerdict, WireAnswer, CallAnswer, TradeVerdict):
        undocumented = [n for n, f in schema.model_fields.items() if not f.description]
        assert not undocumented, f"{schema.__name__} fields missing descriptions: {undocumented}"


# ── TradeProposal ───────────────────────────────────────────────────────


def test_both_sides_populated_is_valid() -> None:
    assert TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"]).is_valid


def test_one_sided_proposals_are_invalid() -> None:
    assert not TradeProposal(giving=["LeBron James"], receiving=[]).is_valid
    assert not TradeProposal(giving=[], receiving=["Jayson Tatum"]).is_valid


def test_empty_proposal_is_invalid() -> None:
    """This is what the AI parser returns when it fails, so it must be falsy."""
    assert not TradeProposal().is_valid
