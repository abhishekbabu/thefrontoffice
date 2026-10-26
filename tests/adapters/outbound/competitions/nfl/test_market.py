"""Tests for finding trades worth offering: `nfl/market.py`."""

from dataclasses import replace

from conftest import SLEEPER_USER_ID, FakeSleeper, _proj, _provider

from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta, SleeperRoster
from thefrontoffice.domain.models import TradeMarket

# You hold two quarterbacks and no receiver; they hold receivers and no quarterback.
PROJECTIONS = {
    "qb1": _proj("qb1", "Star QB", "QB", 22.0),
    "qb2": _proj("qb2", "Spare QB", "QB", 15.0),
    "rb1": _proj("rb1", "Good RB", "RB", 18.0),
    "wr1": _proj("wr1", "Top WR", "WR", 14.0),
    "wr2": _proj("wr2", "Next WR", "WR", 12.0),
    "wr3": _proj("wr3", "Third WR", "WR", 10.0),
    "k1": _proj("k1", "Big Leg", "K", 9.0),
    "k2": _proj("k2", "Short Leg", "K", 7.0),
}


def _client(week: int = 7, deadline: int = 11, **mine: list[str]) -> FakeSleeper:
    client = FakeSleeper(
        projections=PROJECTIONS,
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=["qb1", "qb2", "rb1", "k2"],
                starter_ids=["qb1", "rb1"],
                reserve_ids=mine.get("reserve", []),
                wins=3,
            ),
            SleeperRoster(
                roster_id=2, owner_id="user-2", player_ids=["wr1", "wr2", "wr3", "k1"], starter_ids=[], wins=3
            ),
        ],
        matchups=[{"roster_id": 1, "matchup_id": 1}, {"roster_id": 2, "matchup_id": 1}],
    )
    client.players_catalog = {
        pid: PlayerMeta(player_id=pid, name=p.name, position=p.position) for pid, p in PROJECTIONS.items()
    }
    client.week = week
    client.league = replace(client.league, playoff_teams=1, playoff_week_start=10, trade_deadline=deadline)
    return client


def _market(client: FakeSleeper) -> TradeMarket:
    market = _provider(client).trade_market("L1")
    assert market is not None
    return market


def test_a_spare_at_one_position_is_offered_for_what_they_have_at_another() -> None:
    best, *_ = _market(_client()).options

    assert (best.giving, best.receiving, best.team_id) == (("Spare QB (QB)",), ("Top WR (WR)",), "2")
    assert best.points > 0 and best.their_points > 0


def test_every_trade_offered_helps_both_lineups_and_the_best_for_you_comes_first() -> None:
    options = _market(_client()).options

    assert all(o.points > 0 and o.their_points > 0 for o in options)
    assert [o.points for o in options] == sorted((o.points for o in options), reverse=True)


def test_a_trade_rescores_both_teams_from_the_week_after_this_one() -> None:
    """It lands after the league's review, by which time this week's lineups are set."""
    option, *_ = _market(_client()).options

    assert {(row.team_id, row.week) for row in option.scoring} == {(t, w) for t in ("1", "2") for w in (8, 9)}


def test_a_kicker_is_never_traded_for() -> None:
    """Both sides stream one from the wire, so the better kicker is not on offer."""
    options = _market(_client()).options

    assert not any("(K)" in name for option in options for name in option.giving + option.receiving)


def test_a_player_in_injured_reserve_is_not_offered() -> None:
    options = _market(_client(reserve=["qb2"])).options

    assert not any("Spare QB (QB)" in option.giving for option in options)


def test_a_trade_only_you_gain_from_is_not_offered() -> None:
    client = _client()
    # With a quarterback of their own, your spare does nothing for them.
    client.rosters[1] = replace(client.rosters[1], player_ids=[*client.rosters[1].player_ids, "qb9"])
    client.players_catalog = {
        **(client.players_catalog or {}),
        "qb9": PlayerMeta(player_id="qb9", name="Their QB", position="QB"),
    }
    client.projections = {**PROJECTIONS, "qb9": _proj("qb9", "Their QB", "QB", 20.0)}

    assert _market(client).options == ()


def test_past_the_deadline_there_is_no_market() -> None:
    assert _provider(_client(week=8, deadline=7)).trade_market("L1") is None


def test_the_last_week_before_the_playoffs_has_nothing_left_for_a_trade_to_change() -> None:
    assert _provider(_client(week=9)).trade_market("L1") is None
