"""Tests for a player's career as a drawer says it: `competitions/careers.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.careers import experience, recent_seasons


@pytest.mark.parametrize(("years", "said"), [(0, "rookie"), (1, "1 season"), (7, "7 seasons")])
def test_experience_reads_as_said(years: int, said: str) -> None:
    assert experience(years) == said


def test_the_seasons_shown_are_the_two_before_this_one_newest_first() -> None:
    assert recent_seasons("2026") == ["2025", "2024"]
    assert recent_seasons("pre") == []
