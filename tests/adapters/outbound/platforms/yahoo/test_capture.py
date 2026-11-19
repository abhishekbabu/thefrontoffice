"""Tests for the browser capture: what it plans, what it stores, and the reader served from it.

A sweep here does what the bookmark does — plan, fetch, hand over, plan again
until nothing is new — against a dict standing in for Yahoo, so the round trip
runs through the real reader and the real parser.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from support.yahoo import (
    league_standings_xml,
    league_xml,
    leagues_xml,
    players_xml,
    roster_xml,
    rostered_xml,
    scoreboard_xml,
    standings_xml,
    team_xml,
    teams_xml,
)

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.capture import (
    CAPTURE_TTL,
    SYNCED,
    YahooCapture,
    YahooGame,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooCaptureMissingError
from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionState
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import Capture, CapturedResponse, CaptureReceipt

SEASON = 2026
GAME = YahooGame(code="nba", season=lambda: SEASON, available=50, leaders={"PTS": "12", "BLK": "18"}, per_stat=5)
KEY = "466.l.1"
LEAGUE = YahooLeague(league_key=KEY, name="Hoops", current_week=2, start_week=1, end_week=3)
LIST = paths.leagues("nba", SEASON).path

YAHOO = {
    LIST: leagues_xml(league_xml(KEY, "Hoops", current=2, start=1, end=3)),
    paths.settings(KEY).path: "<fantasy_content><league><settings/></league></fantasy_content>",
    paths.teams(KEY).path: teams_xml(team_xml("t1", "Mine", mine=True), team_xml("t2", "Theirs")),
    paths.standings(KEY).path: league_standings_xml(
        team_xml("t1", "Mine", mine=True, standings=standings_xml(2, 1, 1, 0, "10")),
        team_xml("t2", "Theirs", standings=standings_xml(1, 2, 0, 0, "12")),
    ),
    paths.available(KEY, GAME.available).path: players_xml("Free Agent", "Waiver Wire"),
    **{read.path: players_xml("Shot Blocker") for read in paths.leaders(KEY, GAME.leaders, GAME.per_stat).values()},
    **{paths.scoreboard(KEY, week).path: scoreboard_xml(start=f"2026-01-0{week}") for week in (1, 2, 3)},
    paths.roster("t1").path: roster_xml(rostered_xml("My Center", "C")),
    paths.roster("t2").path: roster_xml(rostered_xml("Their Guard", "PG", status="GTD")),
}
"""What Yahoo answers each path a sweep asks for."""


def _capture(tmp_path: Path, *, active: bool = True) -> YahooCapture:
    return YahooCapture(JsonDiskCache(tmp_path / "cache"), games=(GAME,), active=active)


def _hand_over(capture: YahooCapture, *responses: CapturedResponse, profile: int = 200) -> CaptureReceipt:
    return capture.ingest(
        Capture(profile=CapturedResponse(path=paths.PROFILE, status=profile, body="<x/>"), responses=list(responses))
    )


def _answer(path: str, yahoo: dict[str, str]) -> CapturedResponse:
    return CapturedResponse(path=path, status=200 if path in yahoo else 404, body=yahoo.get(path, ""))


def _sweep(capture: YahooCapture, yahoo: dict[str, str] = YAHOO) -> list[str]:
    """Every path fetched by a sweep the way the bookmark runs one."""
    fetched: list[str] = []
    keys: list[str] = []
    for _ in range(6):
        todo = [step for step in capture.plan(keys).steps if step.path not in fetched]
        if not todo:
            break
        fetched += [step.path for step in todo]
        _hand_over(capture, *(_answer(step.path, yahoo) for step in todo))
        found = "".join(yahoo.get(step.path, "") for step in todo if not step.league)
        keys = sorted(set(keys) | set(re.findall(r"\d+\.l\.\d+", found)))
    return fetched


# ── planning ────────────────────────────────────────────────────────────


def test_the_first_plan_asks_only_for_the_league_lists(tmp_path: Path) -> None:
    plan = _capture(tmp_path).plan([KEY])

    assert [step.path for step in plan.steps] == [LIST]
    assert plan.base.startswith("https://pub-api-ro.fantasysports.yahoo.com/")
    assert plan.probe == paths.PROFILE


def test_a_league_is_planned_from_its_held_list_before_its_teams_are_known(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _hand_over(capture, _answer(LIST, YAHOO))

    steps = capture.plan([KEY]).steps

    assert {step.path for step in steps if step.league == KEY} == {
        paths.settings(KEY).path,
        paths.teams(KEY).path,
        paths.standings(KEY).path,
        paths.available(KEY, GAME.available).path,
        *(read.path for read in paths.leaders(KEY, GAME.leaders, GAME.per_stat).values()),
        *(paths.scoreboard(KEY, week).path for week in (1, 2, 3)),
    }


def test_a_league_the_list_does_not_name_is_not_planned(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _hand_over(capture, _answer(LIST, YAHOO))

    assert [step.path for step in capture.plan(["466.l.999"]).steps] == [LIST]


def test_a_sweep_fetches_every_teams_roster_once_the_team_list_is_held(tmp_path: Path) -> None:
    fetched = _sweep(_capture(tmp_path))

    assert sorted(fetched) == sorted(YAHOO)


def test_a_finished_week_already_held_is_not_asked_for_again(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _sweep(capture)

    planned = {step.path for step in capture.plan([KEY]).steps}

    assert paths.scoreboard(KEY, 1).path not in planned
    assert {paths.scoreboard(KEY, 2).path, paths.scoreboard(KEY, 3).path} <= planned


# ── the reader, served from the capture ─────────────────────────────────


def test_the_reader_reads_everything_it_needs_from_a_sweep(tmp_path: Path) -> None:
    """The plan and the reader name each response alike, so nothing a sweep fetched is missed."""
    capture = _capture(tmp_path)
    _sweep(capture)
    yahoo = YahooClient(LEAGUE, responses=capture)

    mine = yahoo.get_user_team()
    matchup = yahoo.get_matchup(mine.team_key)

    assert mine.name == "Mine"
    assert [p.name for p in yahoo.roster("t1")] == ["My Center"]
    assert matchup is not None and matchup.opponent.name == "Theirs"
    assert [p.status for p in matchup.opponent_roster] == ["GTD"]
    assert yahoo.pairing("t1", 3) is not None
    assert [(t.name, t.standing.rank if t.standing else 0) for t in yahoo.standings()] == [("Mine", 2), ("Theirs", 1)]
    assert sorted(yahoo.season("t1", [1, 2, 3])) == [1, 2, 3]
    assert yahoo.settings().categories == []
    assert [p.name for p in yahoo.fetch_available(GAME.available)] == ["Free Agent", "Waiver Wire"]
    assert {name: [p.name for p in found] for name, found in yahoo.fetch_top_by_stat(GAME.leaders, 5).items()} == {
        "PTS": ["Shot Blocker"],
        "BLK": ["Shot Blocker"],
    }
    assert capture.find_leagues("nba", SEASON) == [LEAGUE]


def test_nothing_synced_yet_is_an_error_not_an_empty_league(tmp_path: Path) -> None:
    yahoo = YahooClient(LEAGUE, responses=_capture(tmp_path))

    with pytest.raises(YahooCaptureMissingError) as caught:
        yahoo.teams()
    assert caught.value.code == "capture_required"
    with pytest.raises(YahooCaptureMissingError):
        _capture(tmp_path).find_leagues("nba", SEASON)


def test_a_sync_from_before_the_table_was_planned_asks_for_the_sync_again(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _sweep(capture, {path: xml for path, xml in YAHOO.items() if path != paths.standings(KEY).path})
    yahoo = YahooClient(LEAGUE, responses=capture)

    with pytest.raises(YahooCaptureMissingError) as caught:
        yahoo.standings()
    assert caught.value.code == "capture_required"
    assert paths.standings(KEY).path in str(caught.value)


def test_a_week_the_last_sync_did_not_carry_is_an_error(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _sweep(capture)

    with pytest.raises(YahooCaptureMissingError, match=re.escape(paths.scoreboard(KEY, 9).path)):
        YahooClient(LEAGUE, responses=capture).pairing("t1", 9)


def test_a_capture_older_than_its_ttl_no_longer_stands_in_for_yahoo(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    cache.set(paths.teams(KEY).path, YAHOO[paths.teams(KEY).path], now=datetime.now(UTC) - CAPTURE_TTL * 2)

    with pytest.raises(YahooCaptureMissingError):
        YahooClient(LEAGUE, responses=_capture(tmp_path)).teams()


def test_a_player_is_found_by_key_among_every_player_the_league_captured(tmp_path: Path) -> None:
    """A lookup no plan could make is answered from the rosters and pages held, off any roster slot."""
    capture = _capture(tmp_path)
    _sweep(capture)
    yahoo = YahooClient(LEAGUE, responses=capture)
    guard = yahoo.roster("t2")[0]

    [found] = yahoo.players([guard.player_key, "466.p.unknown"])

    assert (found.name, found.status, found.slot) == ("Their Guard", "GTD", "")


def test_a_name_search_matches_part_of_a_name_as_yahoo_does(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _sweep(capture)
    yahoo = YahooClient(LEAGUE, responses=capture)

    assert [p.name for p in yahoo.search_players("wire")] == ["Waiver Wire"]
    assert yahoo.search_players("nobody") == []


def test_a_lookup_in_a_league_never_synced_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(YahooCaptureMissingError):
        YahooClient(LEAGUE, responses=_capture(tmp_path)).players(["466.p.1"])


# ── storing ─────────────────────────────────────────────────────────────


def test_only_what_a_plan_asks_for_is_stored(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    receipt = _hand_over(
        capture,
        _answer(LIST, YAHOO),
        CapturedResponse(path="users;use_login=1/profile/secrets", status=200, body="<x/>"),
        _answer(paths.teams(KEY).path, YAHOO),
    )

    assert receipt.stored == 2  # the list, then the league it names
    assert receipt.leagues == [KEY]
    assert [error.split(":")[0] for error in receipt.errors] == ["users;use_login=1/profile/secrets"]


def test_a_refused_or_unreadable_response_is_reported_and_not_stored(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    _hand_over(capture, _answer(LIST, YAHOO))

    receipt = _hand_over(
        capture,
        CapturedResponse(path=paths.teams(KEY).path, status=999, body=""),
        CapturedResponse(path=paths.settings(KEY).path, status=200, body="<not xml"),
    )

    assert (receipt.stored, len(receipt.errors), receipt.leagues) == (0, 2, [])
    with pytest.raises(YahooCaptureMissingError):
        YahooClient(LEAGUE, responses=capture).teams()


def test_a_sync_fetched_signed_out_is_refused_whole(tmp_path: Path) -> None:
    """Signed out, Yahoo's lists are empty rather than refused; stored, they would read as no leagues."""
    capture = _capture(tmp_path)

    with pytest.raises(InvalidRequestError):
        _hand_over(capture, _answer(LIST, YAHOO), profile=401)

    assert capture.status().synced_at is None


# ── readiness and status ────────────────────────────────────────────────


def test_ready_only_once_a_recent_sync_has_stored_something(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    with pytest.raises(YahooCaptureMissingError):
        capture.ensure_captured()

    _sweep(capture)
    capture.ensure_captured()

    JsonDiskCache(tmp_path / "cache").set(SYNCED, 1, now=datetime.now(UTC) - CAPTURE_TTL - timedelta(days=1))
    with pytest.raises(YahooCaptureMissingError):
        _capture(tmp_path).ensure_captured()


def test_the_status_says_when_it_last_synced_and_which_leagues_it_holds(tmp_path: Path) -> None:
    capture = _capture(tmp_path, active=False)
    assert capture.status().model_dump() == {
        "active": False,
        "synced_at": None,
        "leagues": [],
        "session": None,
    }

    before = datetime.now(UTC)
    _sweep(capture)
    status = capture.status()

    assert status.synced_at is not None and status.synced_at >= before
    assert status.leagues == ["Hoops"]


def test_read_with_the_session_cookie_the_status_says_how_that_is_going(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    state = SessionState(cache, "A1=cookie")
    state.refused()
    state.record()

    status = YahooCapture(cache, games=(GAME,), active=False, session=state).status()

    assert status.session is not None and status.session.expired
