"""Tests for a player's season in the league: `nfl/history.py`."""

from dataclasses import replace

from support.nfl import FakeSleeper, league_client, nfl_provider

from thefrontoffice.adapters.outbound.competitions.nfl.history import FREE_AGENT
from thefrontoffice.adapters.outbound.platforms.sleeper.types import DraftPick, Transaction
from thefrontoffice.domain.models import ActivityRow, PlayerDetail


def _detail(client: FakeSleeper, player_id: str) -> PlayerDetail:
    return nfl_provider(client).player("L1", player_id)


def _history(client: FakeSleeper, player_id: str) -> list[str]:
    """The draft line under the History tab."""
    [group] = [g for g in _detail(client, player_id).groups if g.tab == "History"]
    return [s.value for s in group.stats]


def _moves(client: FakeSleeper, player_id: str) -> list[ActivityRow]:
    return _detail(client, player_id).moves


def _drafted(client: FakeSleeper) -> FakeSleeper:
    client.league = replace(client.league, draft_id="D1", total_rosters=12)
    client.draft_picks = [DraftPick(player_id="qb1", roster_id=2, round=3, pick_no=31)]
    return client


def test_the_drawer_says_whose_roster_he_is_on() -> None:
    client = league_client()

    assert _detail(client, "qb1").owner == "Me"
    assert _detail(client, "rb2").owner != _detail(client, "qb1").owner
    assert _detail(client, "wr9").owner == FREE_AGENT


def test_his_draft_pick_names_the_round_the_pick_and_who_made_it() -> None:
    [drafted] = _history(_drafted(league_client()), "qb1")

    assert "Round 3, pick 7" in drafted
    assert "31st" in drafted


def test_a_player_the_draft_passed_over_reads_as_undrafted() -> None:
    assert _history(_drafted(league_client()), "rb1") == ["Undrafted"]


def test_each_move_is_the_leagues_own_activity_row_oldest_first() -> None:
    client = league_client(
        transactions={
            1: [Transaction(kind="free_agent", roster_ids=[2], adds={"qb1": 2}, drops={}, when=1)],
            2: [Transaction(kind="trade", roster_ids=[1, 2], adds={"qb1": 1}, drops={"qb1": 2}, when=3)],
            3: [Transaction(kind="waiver", roster_ids=[2], adds={}, drops={"rb1": 2}, when=4, bid=7)],
        }
    )
    client.week = 3
    moves = _moves(client, "qb1")

    assert [m.what for m in moves] == ["Free agent", "Trade"]
    assert "↔" in moves[1].who  # both sides, as Activity names them
    assert {m.player_id for m in moves[1].moves} == {"qb1"}


def test_a_claim_carries_its_bid_and_a_drop_names_who_let_him_go() -> None:
    client = league_client(
        transactions={
            1: [Transaction(kind="waiver", roster_ids=[1], adds={"rb1": 1}, drops={"rb2": 1}, when=1, bid=12)]
        }
    )
    client.week = 1

    [claim] = _moves(client, "rb1")
    assert claim.bid == "$12"
    [drop] = _moves(client, "rb2")
    assert drop.who == "Me"


def test_a_week_that_will_not_load_is_left_out_rather_than_failing_the_drawer() -> None:
    client = league_client(
        transactions={2: [Transaction(kind="free_agent", roster_ids=[1], adds={"qb1": 1}, drops={}, when=2)]}
    )
    client.week = 2
    client.unloaded_weeks = {1}
    detail = _detail(client, "qb1")

    assert len(detail.moves) == 1
    assert detail.moves_tab in detail.tabs


def test_the_drawer_is_tabbed_and_each_headline_links_its_article() -> None:
    detail = _detail(league_client(), "qb1")

    assert detail.tabs[0] == "This week"
    assert {g.tab for g in detail.groups} <= {"", *detail.tabs}
    assert {t.tab for t in detail.tables} <= set(detail.tabs)


def test_a_player_is_found_by_part_of_his_name_with_position_club_and_owner() -> None:
    found = nfl_provider(league_client()).search_players("L1", "star")

    assert [ref.player_id for ref in found] == ["qb1"]
    assert found[0].detail.endswith("Me")


def test_an_empty_search_finds_nobody() -> None:
    assert nfl_provider(league_client()).search_players("L1", "  ") == []
