"""Tests for the Yahoo paths every reader and the capture name a response by."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import ScoreboardPace
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Average, PlayerStatus, Timeframe
from thefrontoffice.domain.errors import PlatformError

PACIFIC = ZoneInfo("America/Los_Angeles")


def test_a_league_read_is_kept_under_the_path_yahoo_serves_it_at() -> None:
    read = paths.settings("466.l.1")

    assert (read.query, read.league, read.path) == ("settings", "466.l.1", "league/466.l.1/settings")
    assert paths.standings("466.l.1").path == "league/466.l.1/standings"


def test_a_read_naming_its_own_subject_is_its_own_path() -> None:
    assert paths.roster("466.l.1.t.2").path == "team/466.l.1.t.2/roster"
    assert paths.leagues("nba", 2026).path == "users;use_login=1/games;game_codes=nba;seasons=2026/leagues"


def test_available_players_include_those_on_waivers_by_season_rank() -> None:
    [read] = paths.available("466.l.1", 25)

    assert (
        read.query
        == "players;count=25;status=A;sort=AR;sort_type=season;out=ownership,percent_owned/stats;type=average_lastmonth"
    )


def test_a_deeper_wire_is_a_page_of_25_per_read_the_last_only_as_long_as_needed() -> None:
    reads = paths.available("466.l.1", 60, Timeframe.LAST_WEEK)

    assert [read.query.removesuffix(";out=ownership,percent_owned/stats;type=average_lastmonth") for read in reads] == [
        "players;count=25;status=A;sort=AR;sort_type=lastweek",
        "players;count=25;status=A;sort=AR;sort_type=lastweek;start=25",
        "players;count=10;status=A;sort=AR;sort_type=lastweek;start=50",
    ]


def test_a_search_cannot_reach_past_its_term_into_the_rest_of_the_path() -> None:
    read = paths.search("466.l.1", "  O'Neale;start=5/x ")

    assert read.query == "players;search=O'Neale start 5 x;out=ownership"
    assert read.search == "O'Neale start 5 x"


def test_a_page_with_no_sort_says_none() -> None:
    assert (
        paths.player_page("466.l.1", 5, PlayerStatus.FREE_AGENT, None, None).query
        == "players;count=5;status=FA;out=ownership,percent_owned"
    )


def test_leaders_are_one_read_per_stat_keyed_as_asked() -> None:
    reads = paths.leaders("466.l.1", {"PTS": "12", "BLK": "18"}, per_stat=3)

    assert {name: read.query for name, read in reads.items()} == {
        "PTS": "players;count=3;status=A;sort=12;sort_type=lastweek;out=ownership,percent_owned",
        "BLK": "players;count=3;status=A;sort=18;sort_type=lastweek;out=ownership,percent_owned",
    }


def test_only_a_lookup_by_key_or_name_is_one_no_plan_could_make() -> None:
    assert paths.by_keys("466.l.1", ["466.p.1"]).lookup
    assert paths.search("466.l.1", "James").lookup
    assert not paths.teams("466.l.1").lookup
    assert not paths.standings("466.l.1").lookup


def test_only_the_scoreboard_keeps_its_copy_when_a_refresh_fails() -> None:
    assert paths.scoreboard("466.l.1", 3).keep_on_failure
    assert not paths.roster("466.l.1.t.1").keep_on_failure


def test_a_week_played_is_read_with_each_players_line_over_it_and_kept_long() -> None:
    read = paths.played_roster("466.l.1.t.2", 3)

    assert read.path == "team/466.l.1.t.2/roster;week=3/players/stats;type=week;week=3"
    assert read.ttl > paths.ROSTER_TTL


def test_a_day_is_read_with_each_players_line_from_it_and_held_as_briefly_as_the_score() -> None:
    read = paths.day_roster("466.l.1.t.2", date(2026, 11, 21))

    assert read.path == "team/466.l.1.t.2/roster;date=2026-11-21/players/stats;type=date;date=2026-11-21"
    assert read.ttl == paths.SCOREBOARD_TTL


NOON = datetime(2026, 11, 24, 12, tzinfo=ZoneInfo("America/Los_Angeles"))
"""Midday on the league's own clock, on a Tuesday."""


def test_a_day_to_come_holds_only_while_a_lineup_goes_unchanged_and_the_day_being_played_as_the_score() -> None:
    ahead = paths.day_roster("t", date(2026, 11, 27), NOON)
    today = paths.day_roster("t", date(2026, 11, 24), NOON)

    assert paths.SCOREBOARD_TTL < ahead.ttl < paths.ROSTER_TTL
    assert today.ttl == paths.SCOREBOARD_TTL
    assert not ahead.settled and not today.settled


def test_a_day_past_holds_any_copy_read_once_it_stood_and_none_read_before() -> None:
    """Monday stood at 6am Tuesday: a copy from 7am is held at noon, one from 5am — mid-night — never is."""
    read = paths.day_roster("t", date(2026, 11, 23), NOON)

    stood = datetime.combine(date(2026, 11, 24), paths.DAY_STANDS, tzinfo=NOON.tzinfo)
    assert read.settled
    assert NOON - (stood + timedelta(hours=1)) <= read.ttl < NOON - (stood - timedelta(hours=1))
    assert read.servable == read.ttl


def test_a_day_just_past_is_held_as_briefly_as_the_score_until_it_stands() -> None:
    """At 1am Tuesday the last of Monday's games may still be on."""
    read = paths.day_roster("t", date(2026, 11, 23), NOON.replace(hour=1))

    assert (read.ttl, read.settled) == (paths.SCOREBOARD_TTL, True)


def test_averages_by_key_are_a_read_per_25_players_each_naming_its_keys() -> None:
    keys = [f"466.p.{i}" for i in range(30)]

    first, second = paths.averages("466.l.1", keys, Average.SEASON)

    assert first.path == f"league/466.l.1/players;player_keys={','.join(keys[:25])}/stats;type=average_season"
    assert second.player_keys == tuple(keys[25:])
    assert first.lookup


def test_a_rosters_averages_are_one_read_for_the_team() -> None:
    read = paths.roster_averages("466.l.1.t.2", Average.LAST_MONTH)

    assert read.path == "team/466.l.1.t.2/roster/players/stats;type=average_lastmonth"
    assert not read.lookup


def test_the_leagues_moves_are_one_read_of_the_league() -> None:
    assert paths.transactions("466.l.1").path == "league/466.l.1/transactions"


# ── how long each holds ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("week", "live", "ttl"),
    [
        (5, True, paths.SCOREBOARD_TTL),
        (5, False, paths.QUIET_SCOREBOARD_TTL),
        (4, True, paths.SETTLING_TTL),
        (2, True, paths.FINAL_TTL),
        (6, True, paths.AHEAD_TTL),
    ],
    ids=["playing-live", "playing-quiet", "last-week", "settled", "to-come"],
)
def test_a_scoreboard_holds_as_long_as_its_week_can_still_change(week: int, live: bool, ttl: timedelta) -> None:
    assert paths.scoreboard("466.l.1", week, current=5, live=live).ttl == ttl


def test_a_scoreboard_with_no_week_being_played_known_is_read_as_that_week() -> None:
    assert paths.scoreboard("466.l.1", 2).ttl == paths.SCOREBOARD_TTL


def test_the_top_of_the_wire_is_asked_for_oftener_than_the_rest() -> None:
    first, second = paths.available("466.l.1", 50)

    assert (first.ttl, second.ttl) == (paths.LEADERS_TTL, paths.DEEP_TTL)


def test_a_copy_is_servable_while_a_fresh_one_is_fetched_for_one_ttl_more() -> None:
    assert paths.roster("466.l.1.t.1").servable == 2 * paths.ROSTER_TTL


# ── when a scoreboard can be moving ─────────────────────────────────────


def _pace(at: str, games_on: object = None) -> ScoreboardPace:
    clock = datetime.fromisoformat(at).replace(tzinfo=PACIFIC).astimezone(UTC)
    days = games_on if callable(games_on) else (lambda _: True)
    return ScoreboardPace(PACIFIC, time(9), time(1), games_on=days, clock=lambda: clock)


@pytest.mark.parametrize(
    ("at", "live"),
    [
        ("2026-11-19T08:59", False),
        ("2026-11-19T09:00", True),
        ("2026-11-19T19:30", True),
        ("2026-11-20T00:59", True),
        ("2026-11-20T01:00", False),
        ("2026-11-20T04:00", False),
    ],
    ids=["before-tipoff", "first-tipoff", "evening", "past-midnight", "last-whistle", "small-hours"],
)
def test_a_scoreboard_is_live_only_inside_game_hours(at: str, live: bool) -> None:
    assert _pace(at).live() is live


def test_the_hours_past_midnight_belong_to_the_day_they_opened_on() -> None:
    asked: list[date] = []

    def games_on(day: date) -> bool:
        asked.append(day)
        return True

    _pace("2026-11-20T00:30", games_on).live()

    assert asked == [date(2026, 11, 19)]


def test_a_day_without_games_is_quiet_all_day() -> None:
    assert _pace("2026-11-26T19:00", lambda _: False).live() is False


def test_a_schedule_that_will_not_load_reads_the_scoreboard_as_live() -> None:
    def broken(_: date) -> bool:
        raise PlatformError("schedule down")

    assert _pace("2026-11-19T19:00", broken).live() is True


def test_hours_that_close_the_same_day_they_open() -> None:
    clock = datetime(2026, 11, 19, 15, tzinfo=UTC)
    pace = ScoreboardPace(UTC, time(12), time(18), clock=lambda: clock)

    assert pace.live() is True
    assert ScoreboardPace(UTC, time(16), time(18), clock=lambda: clock).live() is False


@pytest.mark.parametrize(
    ("path", "dropped"),
    [
        ("users;use_login=1/games;game_codes=nba;seasons=2026/leagues", True),
        ("team/466.l.1.t.2/roster", True),
        ("team/466.l.1.t.2/roster;date=2026-11-23/players/stats;type=date;date=2026-11-23", True),
        ("team/466.l.1.t.2/roster;week=3/players/stats;type=week;week=3", False),
        ("league/466.l.1/teams", True),
        ("league/466.l.1/transactions", True),
        ("league/466.l.1/players;count=25;status=A", True),
        ("league/466.l.1/settings", False),
        ("league/466.l.1/scoreboard;week=6", True),
        ("league/466.l.1/scoreboard;week=4", True),
        ("league/466.l.1/scoreboard;week=3", False),
        ("league/466.l.10/teams", False),
        ("team/466.l.10.t.2/roster", False),
        ("session", False),
    ],
)
def test_a_refresh_drops_what_a_move_or_a_new_week_changes(path: str, dropped: bool) -> None:
    """Week 5 being played: last week's scoreboard may still settle, the ones before it never change."""
    assert paths.moves(path, "466.l.1", current_week=5) is dropped


@pytest.mark.parametrize(
    ("day", "dropped"), [(date(2026, 11, 22), False), (date(2026, 11, 23), True), (date(2026, 11, 26), True)]
)
def test_a_refresh_keeps_a_day_that_has_stood_and_drops_any_still_moving(day: date, dropped: bool) -> None:
    """At 1am Tuesday, Sunday has stood; Monday's last games may still be on, and Thursday's lineup can change."""
    now = datetime(2026, 11, 24, 1, tzinfo=ZoneInfo("America/Los_Angeles"))

    assert paths.moves(paths.day_roster("466.l.1.t.2", day).path, "466.l.1", 5, now) is dropped


def test_a_league_whose_week_is_unknown_drops_every_scoreboard() -> None:
    assert paths.moves("league/466.l.1/scoreboard;week=1", "466.l.1", current_week=None)
