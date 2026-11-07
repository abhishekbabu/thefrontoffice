"""Tests for the Sleeper provider's trade context."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from support.nfl import DEFAULT_PROJECTIONS, SLEEPER_USER_ID, FakeESPN, FakeSleeper, nfl_provider, proj

from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    SleeperMatchup,
    SleeperRoster,
)
from thefrontoffice.domain.models import TradeProposal


def _client(**kwargs: Any) -> FakeSleeper:
    projections = dict(DEFAULT_PROJECTIONS)
    projections["wr7"] = proj("wr7", "Trade Target", "WR", 15.5, team="KC")
    return FakeSleeper(projections=projections, **kwargs)


def _context(giving: list[str], receiving: list[str], client: FakeSleeper | None = None) -> Any:
    proposal = TradeProposal(giving=giving, receiving=receiving)
    return nfl_provider(client or _client()).build_trade_context("L1", proposal)


# ── resolution ──────────────────────────────────────────────────────────


def test_both_sides_are_resolved_and_priced() -> None:
    context = _context(["Bad RB"], ["Trade Target"])
    assert "Bad RB" in context.prompt
    assert "Trade Target" in context.prompt
    assert "15.5" in context.prompt  # his projection, which is what he is priced at


def test_a_player_with_no_projection_is_still_tradeable() -> None:
    """A bye or a stash has no projection but can still be dealt."""
    context = _context(["Bye Guy"], ["Trade Target"])
    assert "Bye Guy" in context.prompt


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
            SleeperMatchup(roster_id=1, matchup_id=7, points=60.2),
            SleeperMatchup(roster_id=2, matchup_id=7, points=71.8),
        ],
        rosters=[
            SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1"]),
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


# ── designations ────────────────────────────────────────────────────────


def _reported(name: str, team: str, status: str) -> FakeESPN:
    """ESPN's injury report, naming one player."""
    report = InjuryReport(name=name, club=team, status=status, updated=datetime(2026, 9, 22, tzinfo=UTC))
    return FakeESPN(injuries=[report])


def test_a_player_traded_for_carries_the_designation_the_latest_injury_report_gives_him() -> None:
    """Sleeper still lists him healthy; ESPN's report, which every other view reads, has ruled him out."""
    client = _client()
    client.players_catalog = {
        **client.get_nfl_players(),
        "wr7": PlayerMeta(player_id="wr7", name="Trade Target", position="WR", team="KC"),
    }
    proposal = TradeProposal(giving=["Bad RB"], receiving=["Trade Target"])

    context = nfl_provider(client, _reported("Trade Target", "KC", "Out")).build_trade_context("L1", proposal)

    [target] = [line for line in context.prompt.splitlines() if "Trade Target" in line and "proj pts" in line]
    assert "[Out]" in target


def test_a_rostered_player_the_report_clears_is_not_flagged_on_your_roster() -> None:
    client = _client()
    client.projections = {**client.projections, "rb1": replace(client.projections["rb1"], injury_status="Out")}
    proposal = TradeProposal(giving=["Bad RB"], receiving=["Trade Target"])

    context = nfl_provider(client, _reported("Good RB", "BUF", "Active")).build_trade_context("L1", proposal)

    assert "[Out]" not in context.roster_lines["Good RB"]
