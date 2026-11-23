"""Tests for the league season's models."""

from thefrontoffice.domain.models import outcome, record


def test_a_played_matchup_ends_won_lost_or_drawn() -> None:
    """Level scores are a draw, not a loss."""
    assert [outcome(*scores) for scores in ((90, 80), (80, 90), (85.5, 85.5))] == ["won", "lost", "drawn"]


def test_a_record_names_ties_only_where_there_were_any() -> None:
    assert (record(4, 2), record(4, 2, 1)) == ("4-2", "4-2-1")
