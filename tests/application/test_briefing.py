"""Tests for what a follow-up conversation is seeded with: `application/briefing.py`."""

from support.reports import MOCK_NBA_REPORT

from thefrontoffice.application import briefing
from thefrontoffice.domain.models import CompetitionContext, TradeProposal

NAMED = MOCK_NBA_REPORT.moves[0]


def _context() -> CompetitionContext:
    return CompetitionContext(
        prompt="the whole prompt",
        situation="SITUATION: up 5-4",
        constraints="ADDS: 2 left",
        roster_lines={"Mine": "- Mine (C, LAL)\n", NAMED.replaces: f"- {NAMED.replaces} (G, BOS)\n"},
        candidate_lines={NAMED.player: f"- {NAMED.player} line\n", "Passed Over": "- Passed Over line\n"},
    )


def test_a_report_briefing_carries_the_situation_constraints_and_roster() -> None:
    text = briefing.of_report(_context(), MOCK_NBA_REPORT)

    assert "SITUATION: up 5-4" in text
    assert "ADDS: 2 left" in text
    assert "- Mine (C, LAL)" in text


def test_a_report_briefing_carries_only_the_candidates_the_report_named() -> None:
    text = briefing.of_report(_context(), MOCK_NBA_REPORT)

    assert f"- {NAMED.player} line" in text
    assert "Passed Over" not in text


def test_a_report_briefing_says_the_pool_was_left_out() -> None:
    """So the model declines a question about a player it cannot see, rather than inventing his numbers."""
    assert briefing.LEFT_OUT in briefing.of_report(_context(), MOCK_NBA_REPORT)


def test_blank_sections_leave_no_gap() -> None:
    assert briefing.sections("a", "", "  ", "b\n") == "a\n\nb"


TRADE = TradeProposal(giving=["Given Away"], receiving=["Taken In"])


def test_a_trade_briefing_carries_the_situation_roster_and_both_sides_but_not_the_prompt() -> None:
    text = briefing.of_trade(_context(), TRADE)

    assert all(
        part in text for part in ("SITUATION: up 5-4", "ADDS: 2 left", "- Mine (C, LAL)", "Given Away", "Taken In")
    )
    assert "the whole prompt" not in text
    assert "Passed Over" not in text


def test_a_trade_briefing_says_what_was_left_out() -> None:
    assert briefing.TRADE_LEFT_OUT in briefing.of_trade(_context(), TRADE)


def test_a_briefing_without_roster_lines_heads_no_empty_roster() -> None:
    """A roster heading over nothing reads as a manager with no players, which the model then reasons from."""
    bare = CompetitionContext(prompt="p", situation="SITUATION")

    assert "ROSTER" not in briefing.of_trade(bare, TRADE)
    assert "ROSTER" not in briefing.of_report(bare, MOCK_NBA_REPORT)
