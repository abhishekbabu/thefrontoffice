"""Tests for the weeks ahead: `nfl/outlook.py`."""

from dataclasses import replace

import pytest
from support.nfl import SLEEPER_USER_ID, FakeSleeper, nfl_provider, proj

from thefrontoffice.adapters.outbound.competitions.nfl import outlook
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import current_lineup
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import lineup_value
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta, ScheduledGame, SleeperRoster
from thefrontoffice.domain.errors import TeamNotFoundError
from thefrontoffice.domain.models import Outlook, PlayerQuery, WeekAhead

MINE = {
    "qb1": proj("qb1", "Star QB", "QB", 22.0),
    "rb1": proj("rb1", "Good RB", "RB", 18.0),
    "rb2": proj("rb2", "Bad RB", "RB", 4.0),
    "wr8": proj("wr8", "Steady WR", "WR", 10.0, team="MIA", opp="BUF"),
}
WIRE = {
    "qb9": proj("qb9", "Spare QB", "QB", 16.0, team="NYJ", opp="MIA"),
    "rb9": proj("rb9", "Spare RB", "RB", 12.0, team="NYJ", opp="MIA"),
}
BYE_WEEK = 5
"""Buffalo's bye: three of your four on the sideline at once."""


def _client(
    roster_positions: list[str] | None = None, reserve: list[str] | None = None, injured: dict[str, str] | None = None
) -> FakeSleeper:
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
        pid: PlayerMeta(
            player_id=pid, name=p.name, position=p.position, team=p.team, injury_status=(injured or {}).get(pid, "")
        )
        for pid, p in {**MINE, **WIRE}.items()
    }
    client.league = replace(client.league, roster_positions=roster_positions or ["QB", "RB", "WR", "BN"])
    return client


def _weeks(client: FakeSleeper) -> dict[int, WeekAhead]:
    return {w.week: w for w in nfl_provider(client).weeks_ahead("L1").weeks}


def test_the_next_four_weeks_are_projected_soonest_first() -> None:
    assert list(_weeks(_client())) == [4, 5, 6, 7]


def test_a_week_byes_leave_short_says_so_and_who_is_missing() -> None:
    outlook = nfl_provider(_client()).weeks_ahead("L1")
    [week] = [w for w in outlook.weeks if w.week == BYE_WEEK]

    assert outlook.usual is not None and week.short and week.points < outlook.usual
    assert week.short_by == outlook.usual - week.points
    assert {"Star QB (bye)", "Good RB (bye)"} <= set(week.missing)


def test_a_short_week_carries_the_pickup_that_adds_most_to_it() -> None:
    week = _weeks(_client())[BYE_WEEK]

    assert "Spare QB" in week.fix
    assert week.gain == 16.0


def test_a_full_roster_names_who_to_drop_and_it_is_never_a_regular_away_for_the_week() -> None:
    week = _weeks(_client())[BYE_WEEK]

    assert "Bad RB" in week.fix
    assert not any(name in week.fix for name in ("Star QB", "Good RB", "Steady WR"))


def test_a_handcuff_named_as_the_drop_says_whose_he_is() -> None:
    client = _client()
    catalog = client.players_catalog or {}
    catalog["rb1"] = replace(catalog["rb1"], depth_chart_order=1)
    catalog["rb2"] = replace(catalog["rb2"], depth_chart_order=2)

    fix = _weeks(client)[BYE_WEEK].fix

    assert "Bad RB" in fix and "handcuff" in fix


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

    assert nfl_provider(client).weeks_ahead("L1") == Outlook()


def test_a_plain_out_costs_none_of_the_weeks_ahead() -> None:
    """The report sets it for this week's game; after that, the projection Sleeper keeps publishing is the better guess."""
    weeks = _weeks(_client(injured={"rb1": "Out"}))

    assert weeks[4].missing == [] and weeks[4].points == 50.0


def test_a_long_ruling_covers_every_week() -> None:
    weeks = _weeks(_client(injured={"rb1": "IR"}))

    assert all("Good RB (ir)" in weeks[w].missing for w in (4, 6, 7))


def test_the_pickup_is_for_a_position_the_week_is_without() -> None:
    """Short of a running back and a quarterback, the fix is one of those, whatever else the wire holds."""
    client = _client()
    client.weekly_projections[BYE_WEEK]["wr9"] = proj("wr9", "Big WR", "WR", 30.0, team="NYJ", opp="MIA")
    client.players_catalog = {
        **(client.players_catalog or {}),
        "wr9": PlayerMeta(player_id="wr9", name="Big WR", position="WR", team="NYJ"),
    }

    assert "Big WR" not in _weeks(client)[BYE_WEEK].fix


def test_a_pickup_that_barely_helps_is_not_offered() -> None:
    client = _client()
    client.weekly_projections[BYE_WEEK] = {
        "wr8": replace(MINE["wr8"], opponent="NYJ"),
        "rb9": proj("rb9", "Spare RB", "RB", 1.0, team="NYJ", opp="MIA"),
    }

    week = _weeks(client)[BYE_WEEK]

    assert week.short and week.fix == ""


def test_a_player_the_lineup_leans_on_in_one_of_these_weeks_is_never_the_drop() -> None:
    """Bad RB starts while Good RB is on injured reserve, so he is not the spare he looks like."""
    week = _weeks(_client(injured={"rb1": "IR"}))[BYE_WEEK]

    assert "Bad RB" not in week.fix


# ── next week, on the to-do list ────────────────────────────────────────


def _todo(client: FakeSleeper) -> list:
    client.week = BYE_WEEK - 1
    actions = nfl_provider(client).summary("L1").actions
    assert actions is not None
    return actions


def test_a_short_week_next_week_is_on_the_to_do_list() -> None:
    [short] = [a for a in _todo(_client()) if a.key.startswith("short:")]

    assert (short.kind, short.when) == ("waiver", f"week {BYE_WEEK}")


def test_the_short_week_stands_in_for_that_weeks_bye_items() -> None:
    """It names the byes itself, so the bye items would say the same thing twice."""
    assert not [a for a in _todo(_client()) if a.key.startswith(f"bye:{BYE_WEEK}:")]


def test_a_short_week_further_out_stays_on_my_team() -> None:
    client = _client()
    client.week = BYE_WEEK - 2
    actions = nfl_provider(client).summary("L1").actions or []

    assert not [a for a in actions if a.key.startswith("short:")]


def test_any_teams_weeks_ahead_read_its_own_roster() -> None:
    """A rival holding only the wideout off BUF is short nobody on Buffalo's bye."""
    client = _client()
    mine = client.rosters[0]
    client.rosters = [mine, replace(mine, roster_id=2, owner_id="them", player_ids=["wr8"], starter_ids=["wr8"])]
    theirs = {w.week: w for w in nfl_provider(client).weeks_ahead("L1", "2").weeks}

    assert not any("Star QB (bye)" in w.missing for w in theirs.values())
    assert any("Star QB (bye)" in w.missing for w in _weeks(client).values())


def test_a_team_the_league_does_not_have_is_not_found() -> None:
    with pytest.raises(TeamNotFoundError):
        nfl_provider(_client()).weeks_ahead("L1", "99")


# ── the rest of the season ──────────────────────────────────────────────


def _rest(client: FakeSleeper, start: int, teams: int = 4) -> dict[str, float]:
    """This week is 3; four teams play two rounds from `start`. How the round types lengthen the bracket is `test_rules.py`'s."""
    client.league = replace(client.league, playoff_week_start=start, playoff_teams=teams)
    page = nfl_provider(client).free_agents("L1", PlayerQuery())
    return {card.player_id: card.values["ROS"] for card in page.players if "ROS" in card.values}


def test_the_rest_of_the_season_sums_the_weeks_after_this_one_through_the_final() -> None:
    """Playoffs in weeks 6 and 7: weeks 4 to 7, this week (3) left to Proj."""
    client = _client()
    client.weekly_projections[3] = {"rb9": replace(WIRE["rb9"], points=99.0)}

    assert _rest(client, start=6)["rb9"] == 4 * WIRE["rb9"].points


def test_a_week_he_is_not_projected_in_adds_nothing_to_the_rest_of_his_season() -> None:
    """Spare RB byes in week 5: one week of four is nought, not his average."""
    client = _client()
    client.weekly_projections[BYE_WEEK] = {"qb9": WIRE["qb9"]}

    assert _rest(client, start=6)["rb9"] == 3 * WIRE["rb9"].points


def test_the_final_week_is_the_rest_of_the_season_on_its_own() -> None:
    """Two teams play one round, in week 3: nothing of the league's is left after it."""
    client = _client()
    client.weekly_projections[4] = {"rb9": replace(WIRE["rb9"], points=99.0)}

    assert _rest(client, start=3, teams=2)["rb9"] == WIRE["rb9"].points


def test_a_week_that_will_not_load_leaves_the_rest_of_the_season_out_rather_than_short() -> None:
    client = _client()
    client.unloaded_weeks = {5}

    assert _rest(client, start=6) == {}


def test_a_short_weeks_drop_is_never_one_the_rest_of_the_list_already_names() -> None:
    """Healing WR's IR move drops Bad RB, the weakest; the short week's pickup drops the next, Spare WR (idle this
    week, so no other item starts him)."""
    spare = proj("wr3", "Spare WR", "WR", 6.0, team="KC", opp="")
    healing = proj("wr7", "Healing WR", "WR", 7.0, team="KC", opp="LV")
    client = _client(roster_positions=["QB", "RB", "WR", "BN", "BN", "IR"])
    roster = client.rosters[0]
    client.rosters = [
        replace(roster, player_ids=[*roster.player_ids, "wr3", "wr7"], reserve_ids=["wr7"], ir_ids=["wr7"])
    ]
    client.projections = {**client.projections, "wr3": spare, "wr7": healing}
    catalog = client.players_catalog or {}
    catalog["wr3"] = PlayerMeta(player_id="wr3", name=spare.name, position="WR", team="KC")
    catalog["wr7"] = PlayerMeta(
        player_id="wr7", name=healing.name, position="WR", team="KC", injury_status="Questionable"
    )

    actions = _todo(client)
    [activate] = [a for a in actions if a.key.startswith("ir:")]
    [short] = [a for a in actions if a.key.startswith("short:")]

    assert activate.drop == "rb2"
    assert "Spare WR" in short.reason and "Bad RB" not in short.reason


def test_a_players_rate_ahead_counts_only_the_weeks_he_is_projected_in() -> None:
    """Spare RB byes in week 5: 12 a game in the weeks he plays, not 9 over four."""
    client = _client()
    client.weekly_projections[BYE_WEEK] = {"qb9": WIRE["qb9"]}
    state = _state(client)

    assert outlook.rates(client, state)["rb9"] == WIRE["rb9"].points
    assert "rb9" not in outlook.rates(client, replace(state, week=18))


def _state(client: FakeSleeper) -> Week:
    projected = list(MINE.values())
    return Week(
        league=client.league,
        roster=client.rosters[0],
        week=3,
        season="2026",
        projections={**MINE, **WIRE},
        players=client.get_nfl_players(),
        projected=projected,
        lineup=current_lineup(client.league.starting_slots, client.rosters[0].starter_ids, projected),
        rank=lineup_value,
    )


def test_a_starter_in_your_lineup_as_set_is_dropped_only_once_no_bench_player_is_left() -> None:
    """You start Bad RB, though the best lineup would not: Spare WR on the bench goes before him."""
    client = _client(roster_positions=["QB", "RB", "WR", "BN", "BN"])
    roster = client.rosters[0]
    client.rosters = [replace(roster, player_ids=[*roster.player_ids, "wr3"], starter_ids=["qb1", "rb2", "wr8"])]
    client.projections = {**client.projections, "wr3": proj("wr3", "Spare WR", "WR", 6.0, team="KC", opp="")}
    catalog = client.players_catalog or {}
    catalog["wr3"] = PlayerMeta(player_id="wr3", name="Spare WR", position="WR", team="KC")

    fix = _weeks(client)[BYE_WEEK].fix

    assert "drop Spare WR" in fix
