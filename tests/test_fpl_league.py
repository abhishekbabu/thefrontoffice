"""Tests for the mini-league as it reads: `premier_league/league.py`."""

from thefrontoffice.adapters.outbound.competitions.premier_league.league import standing

# ── how a standing reads ────────────────────────────────────────────────


def test_a_classic_standing_is_a_position_in_a_field() -> None:
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="Work", rank=3, is_private=True, rank_count=12)
    assert standing(league) == "3 of 12"


def test_a_head_to_head_standing_is_a_placing() -> None:
    """There is no field to be a position in — it is a table of match records."""
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="Hood h2h", rank=1, is_private=True, is_h2h=True)
    assert standing(league) == "1st · head-to-head"


def test_a_missing_field_size_does_not_render_as_zero() -> None:
    """`1 of 0` is worse than saying nothing about the field."""
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="x", rank=4200, is_private=True, rank_count=None)
    assert standing(league) == "4,200"
