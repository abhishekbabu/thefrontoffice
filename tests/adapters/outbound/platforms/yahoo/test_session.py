"""Tests for reading Yahoo with the person's session cookie: what is sent, what a refusal means, and where it is kept.

Yahoo's frontend host is a dict here, so each read runs through the real
reader, the real parser and the real cache.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from support.http import NO_WAIT
from support.logs import capture_logs
from support.yahoo import FakeFrontend, league_xml, leagues_xml, scoreboard_xml, team_xml, teams_xml

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooCapture
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooSessionExpiredError,
    YahooUnavailableError,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.session import (
    SITE,
    SessionResponses,
    SessionState,
    YahooSession,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague

COOKIE = "A1=d=AQABBsecret-session-value; T=z=tokenvalue"
KEY = "466.l.1"
SEASON = 2026
LEAGUE = YahooLeague(league_key=KEY, name="Hoops", current_week=2, start_week=1, end_week=3)
LIST = paths.leagues("nba", SEASON)
TEAMS = teams_xml(team_xml("t1", "Mine", mine=True), team_xml("t2", "Theirs"))
PROFILE = "<fantasy_content><users><user><guid>X</guid></user></users></fantasy_content>"


def _reader(
    tmp_path: Path, frontend: FakeFrontend, cookie: str = COOKIE
) -> tuple[SessionResponses, SessionState, JsonDiskCache]:
    cache = JsonDiskCache(tmp_path / "cache")
    state = SessionState(cache, cookie)
    session = YahooSession(cookie, state=state, http=frontend)
    return SessionResponses(session, state=state, cache=cache, retry=NO_WAIT), state, cache


# ── what is sent ────────────────────────────────────────────────────────


def test_a_league_read_is_fetched_from_the_frontend_host_at_its_path_with_the_cookie(tmp_path: Path) -> None:
    frontend = FakeFrontend(answers={"/teams": TEAMS})
    reader, _, _ = _reader(tmp_path, frontend)

    teams = YahooClient(LEAGUE, responses=reader).teams()

    assert [team.team_key for team in teams] == ["t1", "t2"]
    [(url, headers, redirects)] = frontend.requests
    assert url == f"{paths.FRONTEND}league/{KEY}/teams"
    assert headers["Cookie"] == COOKIE
    assert (headers["Origin"], headers["Referer"]) == (SITE, f"{SITE}/")
    assert "Mozilla" in headers["User-Agent"]
    assert redirects is False


def test_a_read_naming_its_own_subject_is_fetched_without_a_league(tmp_path: Path) -> None:
    frontend = FakeFrontend(answers={"/roster": "<fantasy_content><team><roster/></team></fantasy_content>"})
    reader, _, _ = _reader(tmp_path, frontend)

    YahooClient(LEAGUE, responses=reader).roster("466.l.1.t.2")

    assert frontend.urls == [f"{paths.FRONTEND}team/466.l.1.t.2/roster"]


# ── where it is kept ────────────────────────────────────────────────────


def test_a_fetched_response_is_kept_under_the_key_a_browser_capture_would_keep_it(tmp_path: Path) -> None:
    """Same path, same key: switching between session and browser reads what the other kept."""
    frontend = FakeFrontend(answers={"/teams": TEAMS})
    reader, _, cache = _reader(tmp_path, frontend)
    YahooClient(LEAGUE, responses=reader).teams()

    capture = YahooCapture(cache, games=(), active=True)

    assert capture.raw(paths.teams(KEY)) == TEAMS


def test_a_captured_response_is_read_without_fetching_while_it_holds(tmp_path: Path) -> None:
    frontend = FakeFrontend()
    reader, _, cache = _reader(tmp_path, frontend)
    cache.set(paths.teams(KEY).path, TEAMS)

    teams = YahooClient(LEAGUE, responses=reader).teams()

    assert [team.name for team in teams] == ["Mine", "Theirs"]
    assert frontend.requests == []


def test_a_season_of_scoreboards_is_fetched_in_one_batch(tmp_path: Path) -> None:
    frontend = FakeFrontend(answers={f"scoreboard;week={week}": scoreboard_xml() for week in (1, 2, 3)})
    reader, _, _ = _reader(tmp_path, frontend)

    season = YahooClient(LEAGUE, responses=reader).season("t1", [1, 2, 3])

    assert sorted(season) == [1, 2, 3]
    assert len(frontend.requests) == 3


# ── finding the leagues ─────────────────────────────────────────────────


def test_leagues_are_found_after_the_profile_says_the_session_is_signed_in(tmp_path: Path) -> None:
    frontend = FakeFrontend(answers={paths.PROFILE: PROFILE, LIST.path: leagues_xml(league_xml(KEY, "Hoops"))})
    reader, _, _ = _reader(tmp_path, frontend)

    leagues = reader.find_leagues("nba", SEASON)

    assert [league.league_key for league in leagues] == [KEY]
    assert frontend.urls == [paths.FRONTEND + paths.PROFILE, paths.FRONTEND + LIST.path]


def test_a_signed_out_session_is_refused_before_its_empty_league_list_reads_as_no_leagues(tmp_path: Path) -> None:
    frontend = FakeFrontend(answers={LIST.path: leagues_xml()}, statuses={paths.PROFILE: 401})
    reader, _, _ = _reader(tmp_path, frontend)

    with pytest.raises(YahooSessionExpiredError):
        reader.find_leagues("nba", SEASON)
    assert frontend.urls == [paths.FRONTEND + paths.PROFILE]


def test_a_kept_league_list_needs_no_profile(tmp_path: Path) -> None:
    frontend = FakeFrontend()
    reader, _, cache = _reader(tmp_path, frontend)
    cache.set(LIST.path, leagues_xml(league_xml(KEY, "Hoops")))

    assert [league.name for league in reader.find_leagues("nba", SEASON)] == ["Hoops"]
    assert frontend.requests == []


# ── a refused session ───────────────────────────────────────────────────


@pytest.mark.parametrize("status", [401, 403, 302])
def test_a_refused_cookie_is_a_session_expired_error_offering_settings(tmp_path: Path, status: int) -> None:
    frontend = FakeFrontend(statuses={"/teams": status})
    reader, _, _ = _reader(tmp_path, frontend)

    with pytest.raises(YahooSessionExpiredError) as raised:
        YahooClient(LEAGUE, responses=reader).teams()

    assert raised.value.code == "session_expired"
    assert len(frontend.requests) == 1, "a refusal is not worth a retry"


def test_a_refusal_is_remembered_for_that_cookie_and_not_for_a_fresh_one(tmp_path: Path) -> None:
    reader, state, cache = _reader(tmp_path, FakeFrontend(statuses={"/teams": 401}))
    with pytest.raises(YahooSessionExpiredError):
        YahooClient(LEAGUE, responses=reader).teams()

    assert state.status().expired
    with pytest.raises(YahooSessionExpiredError):
        state.ensure_accepted()
    fresh = SessionState(cache, "A1=fresh")
    assert not fresh.status().expired
    fresh.ensure_accepted()


def test_a_scoreboard_served_stale_still_records_the_refusal(tmp_path: Path) -> None:
    """The kept copy hides the failure from the page; the status must not hide it too."""
    read = paths.scoreboard(KEY, 2)
    reader, state, cache = _reader(tmp_path, FakeFrontend(statuses={"scoreboard;week=2": 401}))
    cache.set(read.path, scoreboard_xml(), now=datetime.now(UTC) - timedelta(days=1))

    assert reader.raw(read) == scoreboard_xml()
    assert state.status().expired


def test_an_accepted_cookie_records_when_it_last_fetched(tmp_path: Path) -> None:
    reader, state, _ = _reader(tmp_path, FakeFrontend(answers={"/teams": TEAMS}))
    assert state.status().fetched_at is None

    YahooClient(LEAGUE, responses=reader).teams()

    status = state.status()
    assert status.fetched_at is not None
    assert not status.expired


def test_an_outage_is_retried_then_reported_as_yahoo_being_down(tmp_path: Path) -> None:
    frontend = FakeFrontend(statuses={"/teams": 503})
    reader, state, _ = _reader(tmp_path, frontend)

    with pytest.raises(YahooUnavailableError):
        YahooClient(LEAGUE, responses=reader).teams()

    assert len(frontend.requests) == NO_WAIT.attempts
    assert not state.status().expired


# ── the cookie stays secret ─────────────────────────────────────────────


@pytest.mark.parametrize("status", [401, 503])
def test_the_cookie_appears_in_no_log_line_or_error(tmp_path: Path, status: int) -> None:
    reader, _, _ = _reader(tmp_path, FakeFrontend(statuses={"/teams": status}))

    with (
        capture_logs("thefrontoffice.adapters.outbound.platforms", logging.DEBUG) as logs,
        pytest.raises(Exception) as raised,
    ):
        YahooClient(LEAGUE, responses=reader).teams()

    for secret in ("secret-session-value", "tokenvalue"):
        assert secret not in logs.text
        assert secret not in str(raised.value)
    stored = "".join(path.read_text() for path in (tmp_path / "cache").glob("*.json"))
    assert "secret-session-value" not in stored
