"""Tests for the Sleeper provider's trade context."""

from typing import Any

import pytest
from test_nfl_provider import DEFAULT_PROJECTIONS, MY_ID, FakeSleeper, _proj, _provider

from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine, SleeperRoster
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import TradeProposal


def _client(**kwargs: Any) -> FakeSleeper:
    projections = dict(DEFAULT_PROJECTIONS)
    projections["wr7"] = _proj("wr7", "Trade Target", "WR", 15.5, team="KC")
    return FakeSleeper(projections=projections, **kwargs)


def _context(giving: list[str], receiving: list[str], client: FakeSleeper | None = None) -> Any:
    proposal = TradeProposal(giving=giving, receiving=receiving)
    return _provider(client or _client()).build_trade_context("L1", proposal)


# ── resolution ──────────────────────────────────────────────────────────


def test_both_sides_are_resolved_and_priced() -> None:
    context = _context(["Bad RB"], ["Trade Target"])
    assert "Bad RB" in context.prompt
    assert "Trade Target" in context.prompt
    assert "15.5 proj pts" in context.prompt


def test_a_name_that_cannot_be_resolved_raises() -> None:
    """Silently dropping one would evaluate a different trade than described."""
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _context(["Bad RB"], ["Notarealplayer"])
    assert excinfo.value.names == ["Notarealplayer"]


def test_every_unresolved_name_is_reported_at_once() -> None:
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _context(["Ghost One"], ["Ghost Two"])
    assert excinfo.value.names == ["Ghost One", "Ghost Two"]


def test_surrounding_whitespace_is_stripped() -> None:
    assert "Trade Target" in _context(["  Bad RB  "], ["  Trade Target  "]).prompt


def test_a_player_with_no_projection_is_still_tradeable() -> None:
    """A bye or a stash has no projection but can still be dealt."""
    context = _context(["Bye Guy"], ["Trade Target"])
    assert "Bye Guy" in context.prompt
    assert "0.0 proj pts" in context.prompt


# ── context ─────────────────────────────────────────────────────────────


def test_the_prompt_names_the_scoring_format() -> None:
    """Every projection is in that currency."""
    assert "Full PPR" in _context(["Bad RB"], ["Trade Target"]).prompt


def test_the_current_roster_is_included() -> None:
    """The roster-awareness rule needs it."""
    context = _context(["Bad RB"], ["Trade Target"])
    assert "Star QB" in context.roster_lines
    assert "Star QB" in context.prompt


def test_the_matchup_is_carried_as_the_situation() -> None:
    client = _client(
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.2},
            {"roster_id": 2, "matchup_id": 7, "points": 71.8},
        ],
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1"]),
            SleeperRoster(roster_id=2, owner_id="user-2", player_ids=[], starter_ids=[]),
        ],
    )
    situation = _context(["Bad RB"], ["Trade Target"], client).situation
    assert "Rival" in situation
    assert "60.2" in situation


def test_both_sides_of_a_trade_are_priced_on_their_role_too() -> None:
    line = NFLGameLine(
        player_id="wr7",
        week=2,
        team="KC",
        opponent="LV",
        position="WR",
        stats={"off_snp": 54, "tm_off_snp": 60, "rec_tgt": 9, "pts_ppr": 19},
    )
    context = _context(["Bad RB"], ["Trade Target"], client=_client(game_lines=[line]))

    assert "90% of snaps" in context.prompt
