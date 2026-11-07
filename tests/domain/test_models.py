"""Tests for the domain's own models."""

from thefrontoffice.domain.models import Move, TradeProposal, Urgency, outcome, record, urgency_rank

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


def test_a_played_matchup_ends_won_lost_or_drawn() -> None:
    """Level scores are a draw, not a loss."""
    assert [outcome(*scores) for scores in ((90, 80), (80, 90), (85.5, 85.5))] == ["won", "lost", "drawn"]


def test_a_move_reads_as_an_instruction_naming_only_a_counterpart_it_takes_out() -> None:
    move = Move(action="START", player="A", position="RB", team="DET", metric="m", rationale="r", replaces="B")
    watch = move.model_copy(update={"action": "MONITOR"})

    assert (move.title, watch.title) == ("Start A over B", "Watch A")


def test_a_record_names_ties_only_where_there_were_any() -> None:
    assert (record(4, 2), record(4, 2, 1)) == ("4-2", "4-2-1")
