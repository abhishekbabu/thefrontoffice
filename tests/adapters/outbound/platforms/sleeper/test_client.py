"""Tests for the Sleeper API client.

Sleeper is public and read-only, so there is no auth to fake — only the HTTP
session and the disk cache.
"""

from pathlib import Path
from typing import Any

import pytest
import requests
from support.http import FakeResponse, FakeSession

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.sleeper.client import (
    RETRY_MAX_ATTEMPTS,
    SleeperClient,
    _is_retryable,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError, SleeperUnavailableError

STATE = {"week": 5, "season": "2026", "season_type": "regular", "display_week": 5}


def _client(
    routes: dict[str, Any], tmp_path: Path, error: Exception | None = None
) -> tuple[SleeperClient, FakeSession]:
    session = FakeSession(routes, error)
    return SleeperClient(cache=JsonDiskCache(tmp_path / "cache"), session=session), session


# ── retry policy ────────────────────────────────────────────────────────


def test_network_failures_and_rate_limits_are_retryable() -> None:
    assert _is_retryable(requests.exceptions.Timeout())
    assert _is_retryable(requests.exceptions.ConnectionError())
    r = requests.Response()
    r.status_code = 429  # Sleeper's documented rate-limit code
    assert _is_retryable(requests.exceptions.HTTPError(response=r))
    r.status_code = 503
    assert _is_retryable(requests.exceptions.HTTPError(response=r))


def test_a_missing_league_is_not_retryable() -> None:
    """A 404 means the league does not exist; retrying only burns rate limit."""
    r = requests.Response()
    r.status_code = 404
    assert not _is_retryable(requests.exceptions.HTTPError(response=r))
    assert not _is_retryable(ValueError("bad json"))


def test_request_failure_becomes_a_domain_error(tmp_path: Path, no_retry_wait: None) -> None:
    client, session = _client({}, tmp_path, error=requests.exceptions.ConnectionError("down"))
    # No connection is Sleeper being down: still its own error, so callers that
    # carry on without Sleeper still catch it, and the outage kind of it.
    with pytest.raises(SleeperUnavailableError):
        client.get_nfl_state()
    assert len(session.requests) == RETRY_MAX_ATTEMPTS  # retried, then gave up


def test_a_transient_failure_then_success_is_retried(tmp_path: Path, no_retry_wait: None) -> None:
    class Flaky(FakeSession):
        def get(self, url: str, timeout: int = 0) -> FakeResponse:
            self.requests.append(url)
            if len(self.requests) == 1:
                raise requests.exceptions.Timeout()
            return FakeResponse(STATE)

    client = SleeperClient(cache=JsonDiskCache(tmp_path / "cache"), session=Flaky({}))
    assert client.get_nfl_state().week == 5


# ── state and user ──────────────────────────────────────────────────────


def test_nfl_state_is_parsed(tmp_path: Path) -> None:
    client, _ = _client({"state/nfl": STATE}, tmp_path)
    state = client.get_nfl_state()
    assert state.week == 5
    assert state.season == "2026"
    assert state.is_regular_season


def test_preseason_is_not_the_regular_season(tmp_path: Path) -> None:
    client, _ = _client({"state/nfl": {**STATE, "season_type": "pre"}}, tmp_path)
    assert not client.get_nfl_state().is_regular_season


def test_state_is_cached_between_calls(tmp_path: Path) -> None:
    """Sleeper asks callers to stay under 1000 requests a minute."""
    client, session = _client({"state/nfl": STATE}, tmp_path)
    client.get_nfl_state()
    client.get_nfl_state()
    assert len(session.requests) == 1


def test_user_lookup_returns_the_id(tmp_path: Path) -> None:
    client, _ = _client({"user/me": {"user_id": "42", "username": "me", "display_name": "Me"}}, tmp_path)
    assert client.get_user("me").user_id == "42"


def test_unknown_user_raises(tmp_path: Path) -> None:
    client, _ = _client({"user/ghost": None}, tmp_path)
    with pytest.raises(SleeperAPIError, match="No Sleeper user"):
        client.get_user("ghost")


# ── scoring format detection ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rec_value", "expected"),
    [(1.0, "pts_ppr"), (0.75, "pts_ppr"), (0.5, "pts_half_ppr"), (0.25, "pts_half_ppr"), (0.0, "pts_std")],
)
def test_scoring_format_is_inferred_from_points_per_reception(rec_value: float, expected: str) -> None:
    """Sleeper never labels the format; getting this wrong ranks every player by
    the wrong currency."""
    assert SleeperClient.detect_scoring_format({"rec": rec_value}) == expected


def test_absent_reception_setting_is_standard() -> None:
    assert SleeperClient.detect_scoring_format({}) == "pts_std"


# ── leagues and rosters ─────────────────────────────────────────────────


LEAGUE_PAYLOAD = [
    {
        "league_id": "L1",
        "name": "Sunday Money",
        "season": "2026",
        "total_rosters": 12,
        "scoring_settings": {"rec": 1.0},
        "roster_positions": ["QB", "RB", "FLEX", "BN"],
    }
]


def test_leagues_are_parsed_with_format_and_slots(tmp_path: Path) -> None:
    client, _ = _client({"leagues/nfl": LEAGUE_PAYLOAD}, tmp_path)
    league = client.get_leagues("42", "2026")[0]
    assert league.scoring_format == "pts_ppr"
    assert league.starting_slots == ["QB", "RB", "FLEX"]  # BN excluded


def test_a_league_carries_its_trade_deadline(tmp_path: Path) -> None:
    payload = [{**LEAGUE_PAYLOAD[0], "settings": {"trade_deadline": 11}}]
    client, _ = _client({"leagues/nfl": payload}, tmp_path)
    assert client.get_leagues("42", "2026")[0].trade_deadline == 11


def test_a_league_with_no_trade_deadline_reads_as_none(tmp_path: Path) -> None:
    client, _ = _client({"leagues/nfl": LEAGUE_PAYLOAD}, tmp_path)
    assert client.get_leagues("42", "2026")[0].trade_deadline == 0


def test_rosters_carry_record_and_bench(tmp_path: Path) -> None:
    payload = [
        {
            "roster_id": 1,
            "owner_id": "42",
            "players": ["a", "b", "c"],
            "starters": ["a"],
            "settings": {"wins": 3, "losses": 1, "ties": 0, "fpts": 412, "fpts_decimal": 50},
        }
    ]
    client, _ = _client({"rosters": payload}, tmp_path)
    roster = client.get_rosters("L1")[0]
    assert roster.record == "3-1"
    assert roster.points_for == pytest.approx(412.5)


def test_a_tie_shows_in_the_record() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.types import SleeperRoster

    assert SleeperRoster(1, "42", [], [], wins=2, losses=1, ties=1).record == "2-1-1"


def test_league_users_map_ids_to_names(tmp_path: Path) -> None:
    payload = [{"user_id": "42", "display_name": "Me"}, {"user_id": "43", "username": "rival"}]
    client, _ = _client({"/users": payload}, tmp_path)
    assert client.get_league_users("L1") == {"42": "Me", "43": "rival"}


# ── players and projections ─────────────────────────────────────────────


def test_catalog_is_trimmed_to_the_fields_used(tmp_path: Path) -> None:
    """The raw response is ~14MB; caching it whole would dominate the file."""
    raw = {"1": {"full_name": "Star QB", "position": "QB", "team": "BUF", "unused": "x" * 500}}
    client, _ = _client({"players/nfl": raw}, tmp_path)
    meta = client.get_players()["1"]
    assert meta["name"] == "Star QB"
    assert "unused" not in meta


def test_catalog_falls_back_to_first_and_last_name(tmp_path: Path) -> None:
    raw = {"1": {"first_name": "Star", "last_name": "QB", "position": "QB"}}
    client, _ = _client({"players/nfl": raw}, tmp_path)
    assert client.get_players()["1"]["name"] == "Star QB"


def test_catalog_skips_malformed_entries(tmp_path: Path) -> None:
    client, _ = _client({"players/nfl": {"1": "not a dict"}}, tmp_path)
    assert client.get_players() == {}


def test_catalog_is_cached(tmp_path: Path) -> None:
    """The docs ask for at most one fetch per day."""
    client, session = _client({"players/nfl": {"1": {"full_name": "A", "position": "QB"}}}, tmp_path)
    client.get_players()
    client.get_players()
    assert len([r for r in session.requests if "players/nfl" in r]) == 1


PROJECTION_PAYLOAD = [
    {
        "player_id": "1",
        "opponent": "MIA",
        "player": {"first_name": "Star", "last_name": "QB", "position": "QB", "team": "BUF"},
        "stats": {"pts_ppr": 22.4, "pts_std": 18.1},
    },
    {"player_id": "2", "player": {"first_name": "No", "last_name": "Proj"}, "stats": {}},
]


def test_projections_are_keyed_by_player_and_use_the_league_currency(tmp_path: Path) -> None:
    client, _ = _client({"projections/nfl": PROJECTION_PAYLOAD}, tmp_path)
    proj = client.get_projections("2026", 1, "pts_ppr")
    assert proj["1"].points == 22.4
    assert proj["1"].opponent == "MIA"
    assert proj["1"].name == "Star QB"


def test_a_different_scoring_format_reads_a_different_field(tmp_path: Path) -> None:
    client, _ = _client({"projections/nfl": PROJECTION_PAYLOAD}, tmp_path)
    assert client.get_projections("2026", 1, "pts_std")["1"].points == 18.1


def test_players_without_a_projection_are_omitted(tmp_path: Path) -> None:
    client, _ = _client({"projections/nfl": PROJECTION_PAYLOAD}, tmp_path)
    assert "2" not in client.get_projections("2026", 1, "pts_ppr")


def test_projection_requests_cover_every_fantasy_position(tmp_path: Path) -> None:
    client, session = _client({"projections/nfl": []}, tmp_path)
    client.get_projections("2026", 1, "pts_ppr")
    url = session.requests[0]
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert f"position[]={position}" in url


def test_projections_are_asked_for_by_sport(tmp_path: Path) -> None:
    """The sport segment is required and its absence is not an error.

    Sleeper answers the path without it with 200 and an empty list, so every
    projection silently became a zero: no points, no opponent, and a lineup
    that read as though no game had been scheduled all season.
    """
    client, session = _client({"projections/nfl": []}, tmp_path)
    client.get_projections("2026", 1, "pts_ppr")
    assert "/projections/nfl/2026/1" in session.requests[0]


def test_injury_status_marks_a_player_questionable(tmp_path: Path) -> None:
    payload = [
        {
            "player_id": "1",
            "player": {"first_name": "Hurt", "last_name": "Guy", "position": "RB", "injury_status": "Questionable"},
            "stats": {"pts_ppr": 9.0},
        }
    ]
    client, _ = _client({"projections/nfl": payload}, tmp_path)
    assert client.get_projections("2026", 1, "pts_ppr")["1"].is_questionable


def test_a_healthy_player_is_not_questionable(tmp_path: Path) -> None:
    client, _ = _client({"projections/nfl": PROJECTION_PAYLOAD}, tmp_path)
    assert not client.get_projections("2026", 1, "pts_ppr")["1"].is_questionable


# ── trending, stats, matchups ───────────────────────────────────────────


def test_trending_players_are_parsed(tmp_path: Path) -> None:
    client, _ = _client({"trending/add": [{"player_id": "1", "count": 500}]}, tmp_path)
    trending = client.get_trending()
    assert trending[0].player_id == "1"
    assert trending[0].count == 500


def test_trending_entries_without_an_id_are_skipped(tmp_path: Path) -> None:
    client, _ = _client({"trending/add": [{"count": 5}]}, tmp_path)
    assert client.get_trending() == []


def test_matchups_pass_through_as_raw_entries(tmp_path: Path) -> None:
    client, _ = _client({"matchups": [{"roster_id": 1, "matchup_id": 3}]}, tmp_path)
    assert client.get_matchups("L1", 3)[0]["matchup_id"] == 3


def test_an_empty_matchup_week_is_an_empty_list(tmp_path: Path) -> None:
    client, _ = _client({"matchups": None}, tmp_path)
    assert client.get_matchups("L1", 3) == []


# ── NBA ─────────────────────────────────────────────────────────────────


NBA_PROJECTION_PAYLOAD = [
    {
        "player_id": "1",
        "opponent": "BOS",
        "date": "2026-01-05T00:00:00Z",
        "player": {"first_name": "Star", "last_name": "Center", "team": "DEN", "position": "C"},
        "stats": {"pts": 25.1, "reb": 12.3, "ast": 8.0, "blk": 0.9, "gp": 1.0},
    },
    {"player_id": "2", "player": {"first_name": "No", "last_name": "Proj"}, "stats": {}},
]


def test_nba_projections_are_per_game_with_a_date(tmp_path: Path) -> None:
    """A category league sums the games inside its matchup period."""
    client, _ = _client({"projections/nba": NBA_PROJECTION_PAYLOAD}, tmp_path)
    rows = client.get_nba_projections("2026", 12)
    assert len(rows) == 1
    assert rows[0].name == "Star Center"
    assert rows[0].date == "2026-01-05"  # truncated from the ISO timestamp
    assert rows[0].opponent == "BOS"
    assert rows[0].stats["reb"] == 12.3


def test_nba_projection_requests_cover_every_position(tmp_path: Path) -> None:
    client, session = _client({"projections/nba": []}, tmp_path)
    client.get_nba_projections("2026", 12)
    url = session.requests[0]
    for position in ("PG", "SG", "SF", "PF", "C"):
        assert f"position[]={position}" in url


def test_players_without_a_points_projection_are_omitted(tmp_path: Path) -> None:
    client, _ = _client({"projections/nba": NBA_PROJECTION_PAYLOAD}, tmp_path)
    assert all(r.player_id != "2" for r in client.get_nba_projections("2026", 12))


def test_out_of_season_yields_no_projections(tmp_path: Path) -> None:
    """Sleeper publishes nothing before opening night."""
    client, _ = _client({"projections/nba": []}, tmp_path)
    assert client.get_nba_projections("2026", 1) == []


def test_state_is_fetched_per_sport(tmp_path: Path) -> None:
    """NBA and NFL are at different points in their seasons."""
    client, session = _client({"state/nba": {**STATE, "season_type": "off"}, "state/nfl": STATE}, tmp_path)
    assert client.get_state("nba").season_type == "off"
    assert client.get_nfl_state().season_type == "regular"
    assert any("state/nba" in r for r in session.requests)
    assert any("state/nfl" in r for r in session.requests)


def test_each_sports_catalog_is_cached_separately(tmp_path: Path) -> None:
    client, session = _client(
        {
            "players/nba": {"1": {"full_name": "Star Center", "position": "C"}},
            "players/nfl": {"2": {"full_name": "Star QB", "position": "QB"}},
        },
        tmp_path,
    )
    assert "1" in client.get_players("nba")
    assert "2" in client.get_players("nfl")
    assert len([r for r in session.requests if "players/" in r]) == 2


# ── the season schedule ─────────────────────────────────────────────────

SEASON_SCHEDULE = [
    {"week": 1, "date": "2026-09-13", "home": "CAR", "away": "CHI", "status": "pre_game"},
    {"week": 1, "date": "2026-09-14", "home": "CIN", "away": "TB", "status": "pre_game"},
    "not-a-game",
]


def test_the_season_schedule_is_read_off_a_different_base_url(tmp_path: Path) -> None:
    """It is not under /v1, unlike everything else the client reads."""
    client, session = _client({"/schedule/nfl/regular/2026": SEASON_SCHEDULE}, tmp_path)

    games = client.get_season_schedule("2026")

    assert [(g.week, g.date, g.away, g.home) for g in games] == [
        (1, "2026-09-13", "CHI", "CAR"),
        (1, "2026-09-14", "TB", "CIN"),
    ]
    assert "/v1/schedule" not in session.requests[0]


def test_a_scheduled_game_knows_which_side_a_club_is_on(tmp_path: Path) -> None:
    client, _ = _client({"/schedule/nfl/regular/2026": SEASON_SCHEDULE}, tmp_path)

    game = client.get_season_schedule("2026")[0]

    assert game.opponent_of("CAR") == ("CHI", True)
    assert game.opponent_of("CHI") == ("CAR", False)
    assert game.opponent_of("DAL") is None


# ── transactions ────────────────────────────────────────────────────────

TRANSACTIONS = [
    {
        "type": "waiver",
        "status": "complete",
        "roster_ids": [1],
        "adds": {"111": 1},
        "drops": {"222": 1},
        "status_updated": 1787026012872,
    },
    # A failed claim is not something that happened.
    {"type": "waiver", "status": "failed", "roster_ids": [2], "adds": {"333": 2}, "drops": None},
]


def test_only_completed_transactions_are_reported(tmp_path: Path) -> None:
    client, _ = _client({"/transactions/1": TRANSACTIONS}, tmp_path)

    moves = client.get_transactions("L1", 1)

    assert [t.kind for t in moves] == ["waiver"]
    assert moves[0].adds == {"111": 1}
    assert moves[0].drops == {"222": 1}
    assert moves[0].when == 1787026012872


def test_a_null_drops_field_reads_as_nothing_dropped(tmp_path: Path) -> None:
    """Sleeper sends null rather than an empty object for a bare add."""
    payload = [{"type": "free_agent", "status": "complete", "roster_ids": [1], "adds": {"9": 1}, "drops": None}]
    client, _ = _client({"/transactions/1": payload}, tmp_path)

    assert client.get_transactions("L1", 1)[0].drops == {}


def test_a_season_of_matchups_comes_back_in_one_call(tmp_path: Path) -> None:
    """Asked one week at a time they are the whole wait on the season view."""
    routes = {f"/matchups/{w}": [{"roster_id": 1, "matchup_id": w}] for w in (1, 2, 3)}
    client, session = _client(routes, tmp_path)

    weeks = client.get_matchups_bulk("L1", [1, 2, 3])

    assert sorted(weeks) == [1, 2, 3]
    assert weeks[2][0]["matchup_id"] == 2
    assert len(session.requests) == 3


def test_a_week_that_does_not_answer_is_an_empty_week_not_a_missing_key(tmp_path: Path) -> None:
    """The caller reads it by week number and must not have to guard each one."""
    client, _ = _client({"/matchups/1": [{"roster_id": 1}]}, tmp_path)

    weeks = client.get_matchups_bulk("L1", [1, 2])

    assert weeks[2] == []


# ── basketball ──────────────────────────────────────────────────────────

NBA_LOGS = [
    {"player_id": "p1", "date": "2026-01-02", "opponent": "LAL", "stats": {"pts": 30.0, "stl": 2.0}},
    {"player_id": "p1", "date": "2026-01-01", "opponent": "GSW", "stats": {"pts": 20.0}},
    # A game he was scheduled for and did not play.
    {"player_id": "p1", "date": "2025-12-30", "opponent": "PHX", "stats": {}},
    # Team totals ride in the same feed.
    {"player_id": "TEAM_DEN", "date": "2026-01-02", "opponent": "LAL", "stats": {"pts": 130.0}},
]


def test_a_game_nobody_played_is_not_a_game_log(tmp_path: Path) -> None:
    """Sleeper files a row for every scheduled game, carrying no stats where
    the player did not appear — and a run of those averaged in as noughts is
    how five DNPs become "recent form"."""
    client, _ = _client({"/stats/nba/2026/1": NBA_LOGS}, tmp_path)

    logs = client.get_nba_game_logs("2026", [1])

    assert [g.date for g in logs["p1"]] == ["2026-01-02", "2026-01-01"]


def test_team_totals_are_not_mistaken_for_a_player(tmp_path: Path) -> None:
    """A team's 130 points is not somebody's line."""
    client, _ = _client({"/stats/nba/2026/1": NBA_LOGS}, tmp_path)

    assert set(client.get_nba_game_logs("2026", [1])) == {"p1"}


def test_game_logs_come_back_newest_first(tmp_path: Path) -> None:
    """So a caller takes the first N rather than sorting them again."""
    client, _ = _client({"/stats/nba/2026/1": NBA_LOGS}, tmp_path)

    assert client.get_nba_game_logs("2026", [1])["p1"][0].date == "2026-01-02"


def test_an_absent_category_is_left_out_rather_than_stored_as_zero(tmp_path: Path) -> None:
    """It is read back as nought; storing it would double the payload."""
    client, _ = _client({"/stats/nba/2026/1": NBA_LOGS}, tmp_path)

    newest, older = client.get_nba_game_logs("2026", [1])["p1"]
    assert newest.get("stl") == 2.0
    assert older.get("stl") == 0.0
    assert "stl" not in older.stats


NBA_SCHEDULE = [
    {"week": 1, "date": "2026-10-20", "home": {"team": "DET"}, "away": {"team": "BOS"}, "status": "pre_game"},
]


def test_the_basketball_schedule_nests_its_clubs_one_level_deeper(tmp_path: Path) -> None:
    """The only difference from football worth a separate reader."""
    client, _ = _client({"/schedule/nba/regular/2026": NBA_SCHEDULE}, tmp_path)

    game = client.get_nba_schedule("2026")[0]

    assert (game.home, game.away, game.status) == ("DET", "BOS", "pre_game")


# ── football game lines ─────────────────────────────────────────────────


def _nfl_row(pid: str, position: str, opponent: str = "LV", **stats: float) -> dict[str, Any]:
    return {"player_id": pid, "team": "KC", "opponent": opponent, "player": {"position": position}, "stats": stats}


NFL_LINES = [
    _nfl_row("wr1", "WR", off_snp=50, tm_off_snp=60, rec_tgt=8, pts_ppr=14.5, rec_yd=88, h1_rec_yd=40),
    _nfl_row("KC", "DEF", pts_ppr=9),
    _nfl_row("TEAM_KC", "TEAM", pts_ppr=0),
    _nfl_row("lb1", "LB", idp_tkl=7),
    _nfl_row("wr2", "WR", opponent="", off_snp=10),
]


def test_game_lines_keep_fantasy_players_with_the_usage_behind_their_points(tmp_path: Path) -> None:
    client, _ = _client({"/stats/nfl/2026/2": NFL_LINES}, tmp_path)

    lines = {line.player_id: line for line in client.get_nfl_game_lines("2026", [2])}

    # A team total, a linebacker and a row with no game are nobody's starter.
    assert set(lines) == {"wr1", "KC"}
    wr = lines["wr1"]
    assert (wr.week, wr.team, wr.opponent, wr.position) == (2, "KC", "LV", "WR")
    assert wr.stats == {"off_snp": 50.0, "tm_off_snp": 60.0, "rec_tgt": 8.0, "pts_ppr": 14.5}


def test_a_week_that_will_not_load_leaves_a_gap_rather_than_failing(tmp_path: Path) -> None:
    client, _ = _client({"/stats/nfl/2026/2": NFL_LINES}, tmp_path)

    lines = client.get_nfl_game_lines("2026", [1, 2])

    assert {line.week for line in lines} == {2}
