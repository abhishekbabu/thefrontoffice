"""Tests for one football week: the lineup, the opponent, and the live score.

Covers `nfl/week.py` and the summary the provider builds from it.
"""

from dataclasses import replace
from typing import Any

import pytest
from support.nfl import (
    DEFAULT_PROJECTIONS,
    SLEEPER_USER_ID,
    FakeESPN,
    FakeSleeper,
    at_week,
    league_client,
    nfl_provider,
    proj,
)
from support.summary import mine

from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
from thefrontoffice.adapters.outbound.competitions.nfl.week import left_in
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.domain.errors import PlayerNotFoundError

# ── the summary, before any report ──────────────────────────────────────


def test_the_summary_carries_the_lineup_and_the_changes() -> None:
    """Every figure in it is already known, so the page need not wait on a model."""
    summary = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1")

    assert [spot.slot for spot in mine(summary).lineup] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    # Good RB sits on the bench while an RB slot stands empty: the one change to make.
    [swap] = summary.swaps
    assert "Good RB" in swap.start and swap.out == ""


def test_a_player_with_no_game_is_flagged_while_others_have_one() -> None:
    client = FakeSleeper(
        projections={**DEFAULT_PROJECTIONS, "bye1": proj("bye1", "Bye Guy", "TE", 0.0, team="LAR", opp="")},
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "bye1"], starter_ids=["qb1", "bye1"]
            )
        ],
    )
    summary = nfl_provider(client).summary("L1")
    spots = {spot.player: spot for spot in mine(summary).lineup + mine(summary).bench}

    assert spots["Bye Guy"].tone == "warning"  # no game, in a week others play
    assert spots["Star QB"].tone == "neutral"  # has an opponent


def test_a_week_nobody_is_scheduled_for_does_not_flag_the_whole_roster() -> None:
    """Before the season opens Sleeper publishes no fixtures, and warning on
    every player turns the page amber over a date rather than a decision."""
    preseason = {pid: proj(pid, p.name, p.position, 0.0, opp="") for pid, p in DEFAULT_PROJECTIONS.items()}
    summary = nfl_provider(FakeSleeper(projections=preseason)).summary("L1")

    assert all(spot.tone == "neutral" for spot in mine(summary).lineup if spot.player != "—")


def test_the_summary_does_not_ask_for_the_waiver_pool() -> None:
    """It is the expensive half of a report and nothing in the header uses it."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.get_trending = lambda *a, **k: pytest.fail("summary must not fetch trending")

    client_summary = nfl_provider(client).summary("L1")

    assert client_summary.headline


def test_the_week_shows_the_team_you_are_playing() -> None:
    """The other half of the only question a week asks."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"], wins=2, losses=1
            ),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=["rb2", "wr9"], starter_ids=["wr9"], wins=3),
        ],
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 96.1},
        ],
    )
    summary = nfl_provider(client).summary("L1")

    assert summary.opponent is not None
    assert [spot.player for spot in summary.opponent.lineup] == ["Waiver WR"]
    assert [spot.player for spot in summary.opponent.bench] == ["Bad RB"]
    assert summary.opponent.points == "96.1"


def test_a_week_with_no_fixture_shows_no_opponent() -> None:
    """A bye is not a nil-nil scoreline."""
    assert nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1").opponent is None


def test_a_player_carries_their_week_and_their_depth() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_players()
    client.players_catalog = {**catalog, "qb1": PlayerMeta(**catalog["qb1"], depth_chart_order=2)}
    detail = nfl_provider(client).player("L1", "qb1")
    labels = {stat.label: stat.value for group in detail.groups for stat in group.stats}

    assert detail.name == "Star QB"
    assert detail.headline == "22.0"
    assert detail.headline_label == "projected for week 3"
    # In full, because a drawer has the room a table column does not.
    assert labels["Opponent"] == "vs Miami Dolphins"
    assert labels["Depth chart"] == "2"


def test_an_unknown_player_is_refused() -> None:
    with pytest.raises(PlayerNotFoundError):
        nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "nobody")


def test_a_projection_is_broken_out_into_the_line_behind_it() -> None:
    """The total is what a lineup is chosen on; this is what makes it believable."""
    projections = {
        "qb1": WeeklyProjection(
            player_id="qb1",
            name="Star QB",
            position="QB",
            team="BUF",
            opponent="MIA",
            points=22.0,
            stats={"pass_yd": 271.0, "pass_td": 1.8, "rush_yd": 18.0, "rec": 0.0},
        )
    }
    groups = {g.title: g for g in nfl_provider(FakeSleeper(projections=projections)).player("L1", "qb1").groups}

    line = {s.label: s.value for s in groups["Projected line"].stats}
    assert line["Pass yards"] == "271"
    assert "Receptions" not in line  # a zero for a quarterback is noise


def test_a_player_with_no_projection_has_no_line_to_break_out() -> None:
    titles = [g.title for g in nfl_provider(FakeSleeper()).player("L1", "qb1").groups]
    assert "Projected line" not in titles


# ── reading the two lineups across ──────────────────────────────────────

FULL_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN"]
FULL_PROJECTIONS = {
    "qb1": proj("qb1", "Star QB", "QB", 22.0),
    "rb1": proj("rb1", "Good RB", "RB", 18.0),
    "rb2": proj("rb2", "Bad RB", "RB", 4.0),
    "wr1": proj("wr1", "WR One", "WR", 15.0),
    "wr2": proj("wr2", "WR Two", "WR", 12.0),
    "te1": proj("te1", "The TE", "TE", 9.0),
    "fx1": proj("fx1", "Flex WR", "WR", 8.0),
    "k1": proj("k1", "The K", "K", 7.0),
    "def1": proj("def1", "The D", "DEF", 6.0),
}
FULL_STARTERS = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "fx1", "k1", "def1"]


def _full_league() -> SleeperLeague:
    return SleeperLeague(
        league_id="L1",
        name="Sunday Money",
        season="2026",
        total_rosters=12,
        scoring_format="pts_ppr",
        roster_positions=FULL_SLOTS,
    )


def _both_sides() -> FakeSleeper:
    return FakeSleeper(
        projections=FULL_PROJECTIONS,
        league=_full_league(),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=FULL_STARTERS, starter_ids=FULL_STARTERS),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=FULL_STARTERS, starter_ids=FULL_STARTERS),
        ],
        matchups=[{"roster_id": 1, "matchup_id": 7}, {"roster_id": 2, "matchup_id": 7, "points": 96.1}],
    )


def test_both_lineups_are_listed_in_the_same_slot_order() -> None:
    """The sides are read across, so an opponent in roster order is not a
    comparison — Sleeper returns `player_ids` in no order at all."""
    summary = nfl_provider(_both_sides()).summary("L1")

    assert summary.opponent is not None
    slots = [spot.slot for spot in summary.opponent.lineup]
    assert slots == [spot.slot for spot in mine(summary).lineup]
    assert slots == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def test_an_off_length_starter_list_is_left_unlabelled() -> None:
    """Positions cannot be trusted once the lists disagree, and a WR labelled
    QB is worse than a row carrying no label at all."""
    client = _both_sides()
    client.rosters[1] = SleeperRoster(roster_id=2, owner_id="them", player_ids=FULL_STARTERS, starter_ids=["wr1"])

    summary = nfl_provider(client).summary("L1")

    assert summary.opponent is not None
    assert [spot.slot for spot in summary.opponent.lineup] == [""]


def test_a_slot_does_not_repeat_the_position_beside_it() -> None:
    """The slot column already says QB; saying it twice reads as two facts."""
    summary = nfl_provider(_both_sides()).summary("L1")

    quarterback = mine(summary).lineup[0]
    assert quarterback.slot == "QB"
    assert not quarterback.detail.startswith("QB")


def test_a_flex_still_says_which_position_is_filling_it() -> None:
    """The one case where place and position genuinely differ."""
    summary = nfl_provider(_both_sides()).summary("L1")

    flex = next(spot for spot in mine(summary).lineup if spot.slot == "FLEX")
    assert flex.detail.startswith("WR")


# ── the week as it is actually going ────────────────────────────────────
# Not reachable with live data outside the season, so the shape of a week in
# progress is only ever exercised here.

KICKED_OFF = [
    ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="complete"),
    ScheduledGame(week=3, date="2026-09-28", home="KC", away="DEN", status="pre_game"),
]


def _live_client(points: dict[str, float]) -> FakeSleeper:
    return FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=KICKED_OFF,
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
        matchups=[{"roster_id": 1, "matchup_id": 4, "players_points": points}],
    )


def test_a_player_whose_game_has_started_shows_what_they_scored() -> None:
    """Every fake projection is a BUF player, and BUF has finished."""
    summary = nfl_provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1")

    values = {spot.player: spot.value for spot in mine(summary).lineup}
    assert values["Star QB"] == "24.5 pts"


def test_a_haul_and_a_blank_are_toned_apart() -> None:
    summary = nfl_provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1")

    tones = {spot.player: spot.tone for spot in mine(summary).lineup}
    assert tones["Star QB"] == "good"
    assert tones["Bad RB"] == "warning"


def test_a_player_whose_game_has_not_kicked_off_keeps_their_projection() -> None:
    """Nought against somebody playing on Monday says they blanked."""
    client = _live_client({"qb1": 0.0})
    client.season_schedule = [ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="pre_game")]

    summary = nfl_provider(client).summary("L1")

    assert all(not spot.value.endswith("pts") for spot in mine(summary).lineup)


def test_the_side_total_switches_from_projected_to_scored() -> None:
    assert mine(nfl_provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1")).points == "27.5 pts"


def test_before_kickoff_the_side_total_is_still_a_projection() -> None:
    client = _live_client({})
    client.season_schedule = [ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="pre_game")]

    assert mine(nfl_provider(client).summary("L1")).points.endswith("proj")


def test_a_missing_scoreboard_falls_back_to_projections() -> None:
    client = _live_client({})
    client.matchups_error = SleeperAPIError("down")

    summary = nfl_provider(client).summary("L1")

    assert summary.mine is not None
    assert mine(summary).points.endswith("proj")


# ── the live scoreboard over a stale schedule ───────────────────────────
# Sleeper's schedule is cached for hours, so a game kicking off now still reads
# as not started there; ESPN's scoreboard is what says it has.

STALE = [ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="pre_game")]
UNDERWAY = [ScoreboardGame("BUF", "MIA", "in", period=3, clock=450.0, label="7:30 - 3rd")]


def _underway(**espn: Any) -> SleeperNFLProvider:
    client = _live_client({"qb1": 6.5, "rb2": 1.0})
    client.season_schedule = STALE
    return SleeperNFLProvider(username="me", client=client, espn=FakeESPN(**espn))


def test_a_game_the_scoreboard_has_under_way_shows_his_points_and_its_clock() -> None:
    qb = next(spot for spot in mine(_underway(scoreboard=UNDERWAY).summary("L1")).lineup if spot.player == "Star QB")

    assert qb.value == "6.5 pts"
    assert "7:30 - 3rd" in qb.detail


def test_the_side_total_counts_a_game_under_way() -> None:
    assert mine(_underway(scoreboard=UNDERWAY).summary("L1")).points == "7.5 pts"


def test_the_forecast_leaves_as_much_of_a_game_as_its_clock_does() -> None:
    """Third quarter, seven and a half minutes left: three-eighths of the game to go."""
    client = _live_client({"qb1": 6.5})
    client.season_schedule = STALE
    client.matchups = [
        {"roster_id": 1, "matchup_id": 4, "players_points": {"qb1": 6.5}, "starters": ["qb1", "rb2"]},
        {"roster_id": 2, "matchup_id": 4, "players_points": {}, "starters": []},
    ]
    client.rosters = [*client.rosters, SleeperRoster(roster_id=2, owner_id="user-2", player_ids=[], starter_ids=[])]
    matchup = SleeperNFLProvider(username="me", client=client, espn=FakeESPN(scoreboard=UNDERWAY)).matchup_input("L1")

    assert matchup is not None
    qb = next(o for o in matchup.mine if o.player_id == "qb1")
    assert (qb.floor, qb.remaining) == (6.5, 0.375)


def test_without_the_scoreboard_the_schedule_stands() -> None:
    summary = _underway(scoreboard_error=ESPNAPIError("down")).summary("L1")

    assert mine(summary).points.endswith("proj")


def test_a_bench_player_in_a_reserve_slot_is_marked_as_such() -> None:
    """He takes no bench spot, which a row reading like every other bench row hides."""

    def bench_detail(reserve: list[str]) -> str:
        client = _live_client({})
        client.rosters = [replace(client.rosters[0], reserve_ids=reserve)]
        return next(s.detail for s in mine(nfl_provider(client).summary("L1")).bench if s.player_id == "rb1")

    assert bench_detail(["rb1"]) != bench_detail([])


# ── who is not playing, and why ─────────────────────────────────────────


def _with_injury(status: str) -> FakeSleeper:
    """Good RB has no projection, as Sleeper publishes none for a player it rules out; BUF still plays."""
    client = _live_client({})
    client.season_schedule = STALE
    client.projections = {pid: p for pid, p in DEFAULT_PROJECTIONS.items() if pid != "rb1"}
    catalog = client.get_players()
    client.players_catalog = {
        **catalog,
        "rb1": PlayerMeta(player_id="rb1", name="Good RB", position="RB", team="BUF", injury_status=status),
    }
    return client


def _bench_detail(client: FakeSleeper) -> str:
    return next(s.detail for s in mine(nfl_provider(client).summary("L1")).bench if s.player_id == "rb1")


def test_a_player_ruled_out_reads_differently_from_one_on_bye() -> None:
    """His club plays: "no game" would send somebody looking for a bye that is not there."""
    assert _bench_detail(_with_injury("Out")) != _bench_detail(_with_injury(""))


def test_a_roster_reads_as_a_lineup_starters_then_bench_then_reserve() -> None:
    client = _live_client({})
    client.rosters = [
        replace(client.rosters[0], player_ids=["rb2", "rb1", "qb1"], starter_ids=["qb1"], reserve_ids=["rb2"])
    ]

    assert [card.player_id for card in nfl_provider(client).roster("L1")] == ["qb1", "rb1", "rb2"]


def test_the_squad_says_why_an_injured_player_sits_too() -> None:
    def opponent(status: str) -> str:
        card = next(c for c in nfl_provider(_with_injury(status)).roster("L1") if c.player_id == "rb1")
        return card.columns["Opponent"]

    assert opponent("Out") != opponent("")


def test_how_much_of_a_game_is_left_follows_its_clock() -> None:
    assert left_in(ScoreboardGame("A", "B", "pre")) == 1.0
    assert left_in(ScoreboardGame("A", "B", "post")) == 0.0
    assert left_in(ScoreboardGame("A", "B", "in", period=2, clock=0.0)) == 0.5  # halftime
    assert left_in(ScoreboardGame("A", "B", "in", period=4, clock=450.0)) == 0.125
    assert left_in(ScoreboardGame("A", "B", "in", period=5, clock=360.0)) == 0.1  # six minutes of overtime


# ── when the week is played ─────────────────────────────────────────────────


def test_the_week_says_when_it_is_played() -> None:
    """A week with no dates on it is a number, which is already known."""
    assert nfl_provider(league_client()).summary("L1").window == "Week 3"


def test_the_window_carries_the_dates_where_there_are_any() -> None:
    assert nfl_provider(at_week(2)).summary("L1").window == "Week 2 · 17 Sep"
