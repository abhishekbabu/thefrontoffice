"""Tests for the weeks ahead: `nfl/outlook.py`."""

from dataclasses import replace

from conftest import SLEEPER_USER_ID, FakeSleeper, _proj, _provider

from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta, ScheduledGame, SleeperRoster
from thefrontoffice.domain.models import WeekAhead

MINE = {
    "qb1": _proj("qb1", "Star QB", "QB", 22.0),
    "rb1": _proj("rb1", "Good RB", "RB", 18.0),
    "rb2": _proj("rb2", "Bad RB", "RB", 4.0),
    "wr8": _proj("wr8", "Steady WR", "WR", 10.0, team="MIA", opp="BUF"),
}
WIRE = {
    "qb9": _proj("qb9", "Spare QB", "QB", 16.0, team="NYJ", opp="MIA"),
    "rb9": _proj("rb9", "Spare RB", "RB", 12.0, team="NYJ", opp="MIA"),
}
BYE_WEEK = 5
"""Buffalo's bye: three of your four on the sideline at once."""


def _client(roster_positions: list[str] | None = None, reserve: list[str] | None = None) -> FakeSleeper:
    client = FakeSleeper(
        projections={**MINE, **WIRE},
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=list(MINE),
                starter_ids=["qb1", "rb1", "wr8"],
                reserve_ids=reserve or [],
            )
        ],
        season_schedule=[
            ScheduledGame(week=w, date="", home="BUF", away="MIA")
            if w != BYE_WEEK
            else ScheduledGame(week=w, date="", home="MIA", away="NYJ")
            for w in range(3, 8)
        ],
    )
    client.weekly_projections[BYE_WEEK] = {"wr8": replace(MINE["wr8"], opponent="NYJ"), **WIRE}
    client.players_catalog = {
        pid: PlayerMeta(player_id=pid, name=p.name, position=p.position, team=p.team)
        for pid, p in {**MINE, **WIRE}.items()
    }
    client.league = replace(client.league, roster_positions=roster_positions or ["QB", "RB", "WR", "BN"])
    return client


def _weeks(client: FakeSleeper) -> dict[int, WeekAhead]:
    return {w.week: w for w in _provider(client).weeks_ahead("L1")}


def test_the_next_four_weeks_are_projected_soonest_first() -> None:
    assert list(_weeks(_client())) == [4, 5, 6, 7]


def test_a_week_byes_leave_short_says_so_and_who_is_missing() -> None:
    week = _weeks(_client())[BYE_WEEK]

    assert week.short and week.points < week.usual
    assert {"Star QB (bye)", "Good RB (bye)"} <= set(week.missing)


def test_a_short_week_carries_the_pickup_that_adds_most_to_it() -> None:
    week = _weeks(_client())[BYE_WEEK]

    assert "Spare QB" in week.fix
    assert week.gain == 16.0


def test_a_full_roster_names_who_to_drop_and_it_is_never_a_regular_away_for_the_week() -> None:
    week = _weeks(_client())[BYE_WEEK]

    assert "Bad RB" in week.fix
    assert not any(name in week.fix for name in ("Star QB", "Good RB", "Steady WR"))


def test_a_roster_with_room_drops_nobody() -> None:
    week = _weeks(_client(roster_positions=["QB", "RB", "WR", "BN", "BN", "BN"]))[BYE_WEEK]

    assert week.fix and "Bad RB" not in week.fix


def test_an_ordinary_week_is_not_short_and_asks_for_nothing() -> None:
    week = _weeks(_client())[6]

    assert (week.short, week.missing, week.fix) == (False, [], "")


def test_a_player_in_a_reserve_slot_is_not_counted_on() -> None:
    """He takes no roster spot, and he is not in any lineup until he comes off it."""
    week = _weeks(_client(reserve=["qb1"]))[6]

    assert week.points == 28.0  # Good RB and Steady WR, without the quarterback


def test_the_last_regular_season_week_has_nothing_ahead() -> None:
    client = _client()
    client.week = 18

    assert _provider(client).weeks_ahead("L1") == []
