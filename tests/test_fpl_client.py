"""Tests for the Fantasy Premier League client.

FPL is public and read-only, so there is nothing to authenticate — only the
HTTP session and the disk cache stand in.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.client import (
    FPLClient,
    free_transfers,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import MAX_FREE_TRANSFERS, GameweekResult
from thefrontoffice.domain.errors import FPLAPIError

BOOTSTRAP = {
    "events": [
        {"id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-14T17:30:00Z", "finished": True, "is_current": True},
        {
            "id": 2,
            "name": "Gameweek 2",
            "deadline_time": "2026-08-21T17:30:00Z",
            "is_next": True,
            "average_entry_score": 51,
        },
        {"id": 3, "name": "Gameweek 3", "deadline_time": "2026-08-28T17:30:00Z"},
    ],
    "teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "MCI"}],
    "elements": [
        {
            "id": 10,
            "web_name": "Saka",
            "first_name": "Bukayo",
            "second_name": "Saka",
            "element_type": 3,
            "team": 1,
            "now_cost": 95,
            "ep_next": "6.4",
            "form": "5.2",
            "points_per_game": "5.0",
            "total_points": 40,
            "selected_by_percent": "31.2",
            "status": "a",
            "minutes": 540,
            "expected_goals": "2.10",
            "expected_assists": "1.40",
            "expected_goal_involvements": "3.50",
            "expected_goals_conceded": "4.00",
            "ict_index": "88.4",
        },
        {
            "id": 11,
            "web_name": "Haaland",
            "first_name": "Erling",
            "second_name": "Haaland",
            "element_type": 4,
            "team": 2,
            "now_cost": 150,
            "ep_next": None,
            "form": None,
            "points_per_game": "8.0",
            "total_points": 64,
            "selected_by_percent": "72.0",
            "status": "d",
            "news": "Knock - 75% chance of playing",
            "chance_of_playing_next_round": 75,
            "minutes": 600,
        },
    ],
}

ENTRY = {
    "id": 77,
    "name": "Front Office FC",
    "player_first_name": "Abhishek",
    "player_last_name": "Babu",
    "summary_overall_points": 412,
    "summary_overall_rank": 340112,
    "current_event": 2,
    "leagues": {
        "classic": [
            {"id": 314, "name": "Overall", "league_type": "s", "entry_rank": 340112, "rank_count": 9000000},
            {"id": 900, "name": "Work League", "league_type": "x", "entry_rank": 3, "rank_count": 12},
        ],
        # Head-to-head is a separate list, and carries no rank_count.
        "h2h": [{"id": 950, "name": "Hood h2h", "league_type": "x", "entry_rank": 1, "rank_count": None}],
    },
}

PICKS = {
    "active_chip": "bboost",
    "picks": [
        {"element": 10, "position": 1, "multiplier": 2, "is_captain": True},
        {"element": 11, "position": 12, "multiplier": 0, "is_vice_captain": True},
    ],
    "entry_history": {"bank": 25, "value": 1004, "event_transfers": 1, "event_transfers_cost": 0, "points_on_bench": 7},
}

HISTORY = {
    "current": [
        {"event": 1, "points": 60, "event_transfers": 0, "event_transfers_cost": 0},
        {"event": 2, "points": 71, "event_transfers": 2, "event_transfers_cost": 4},
    ]
}

FIXTURES = [
    {
        "event": 3,
        "team_h": 1,
        "team_a": 2,
        "team_h_difficulty": 4,
        "team_a_difficulty": 2,
        "kickoff_time": "2026-08-29T14:00:00Z",
    },
    {"event": None, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 5, "kickoff_time": None},
]

ROUTES = {
    "bootstrap-static": BOOTSTRAP,
    "/entry/77/event/": PICKS,
    "/entry/77/history/": HISTORY,
    "/entry/77/": ENTRY,
    "/fixtures/": FIXTURES,
}


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Serves canned payloads by URL substring, most specific route first."""

    def __init__(self, routes: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.routes = ROUTES if routes is None else routes
        self.error = error
        self.requests: list[str] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requests.append(url)
        if self.error:
            raise self.error
        for fragment, payload in self.routes.items():
            if fragment in url:
                return FakeResponse(payload)
        return FakeResponse(None, status=404)


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the hermetic suite fast — the backoff is real seconds otherwise."""
    import thefrontoffice.adapters.outbound.platforms.fpl.client as mod

    original = mod._retry
    monkeypatch.setattr(mod, "_retry", lambda: original().copy(wait=lambda _: 0))


@pytest.fixture
def client(tmp_path: Path) -> FPLClient:
    return FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession())


# ── the bootstrap payload ───────────────────────────────────────────────


def test_teams_map_to_abbreviations(client: FPLClient) -> None:
    assert client.get_teams() == {1: "ARS", 2: "MCI"}


def test_the_bootstrap_is_fetched_once_per_instance(tmp_path: Path) -> None:
    """A report reads it five times; re-parsing a megabyte each time is waste."""
    session = FakeSession()
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)
    client.get_teams()
    client.get_players()
    client.get_gameweeks()
    assert sum("bootstrap" in url for url in session.requests) == 1


def test_an_empty_bootstrap_raises(tmp_path: Path) -> None:
    """A 200 carrying nothing usable is not a transport failure, so it is not retried."""
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession(routes={"bootstrap-static": {}}))
    with pytest.raises(FPLAPIError, match="no player data"):
        client.get_teams()


def test_players_carry_the_games_own_projection(client: FPLClient) -> None:
    saka = client.get_players()[10]
    assert saka.position == "MID"
    assert saka.team == "ARS"
    assert saka.expected_points == 6.4
    assert saka.expected_goal_involvements == 3.5
    assert saka.full_name == "Bukayo Saka"


def test_quoted_and_null_numbers_both_coerce(client: FPLClient) -> None:
    """Form and expected goals arrive quoted, and are null for a player yet to feature."""
    haaland = client.get_players()[11]
    assert haaland.expected_points == 0.0
    assert haaland.form == 0.0
    assert haaland.expected_goals == 0.0


def test_availability_reports_a_doubt(client: FPLClient) -> None:
    assert client.get_players()[11].availability == "doubtful 75%"
    assert client.get_players()[10].availability == ""
    assert client.get_players()[10].is_available


# ── gameweeks ───────────────────────────────────────────────────────────


def test_the_upcoming_gameweek_is_the_next_open_deadline(client: FPLClient) -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    assert client.upcoming_gameweek(now).id == 2


def test_a_passed_deadline_is_never_the_upcoming_gameweek(client: FPLClient) -> None:
    """Once a deadline passes that team is locked, so advice about it is too late."""
    now = datetime(2026, 8, 22, tzinfo=UTC)
    assert client.upcoming_gameweek(now).id == 3


def test_the_last_gameweek_stands_once_the_season_runs_out(client: FPLClient) -> None:
    now = datetime(2027, 6, 1, tzinfo=UTC)
    assert client.upcoming_gameweek(now).id == 3


def test_gameweeks_carry_their_flags(client: FPLClient) -> None:
    first, second, _ = client.get_gameweeks()
    assert first.finished and first.is_current
    assert second.is_next and second.average_score == 51


# ── one manager ─────────────────────────────────────────────────────────


def test_an_entry_separates_private_leagues_from_the_games_own(client: FPLClient) -> None:
    entry = client.get_entry(77)
    assert entry.manager == "Abhishek Babu"
    assert [(lg.name, lg.is_private) for lg in entry.leagues] == [
        ("Overall", False),
        ("Work League", True),
        ("Hood h2h", True),
    ]


def test_head_to_head_leagues_are_read_too(client: FPLClient) -> None:
    """They live in their own list, so a manager whose only invitational league
    is head-to-head has an empty classic list and looks like they have none."""
    h2h = next(lg for lg in client.get_entry(77).leagues if lg.is_h2h)

    assert (h2h.name, h2h.rank, h2h.rank_count) == ("Hood h2h", 1, None)


def test_a_classic_league_is_not_marked_head_to_head(client: FPLClient) -> None:
    assert not next(lg for lg in client.get_entry(77).leagues if lg.name == "Work League").is_h2h


def test_an_unknown_entry_raises(tmp_path: Path) -> None:
    """A 200 carrying nothing usable is not a transport failure, so it is not retried."""
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession(routes={"/entry/77/": {}}))
    with pytest.raises(FPLAPIError, match="No FPL entry"):
        client.get_entry(77)


def test_a_squad_reads_its_picks_and_its_money(client: FPLClient) -> None:
    squad = client.get_squad(77, 2)
    assert squad.bank == 25
    assert squad.value == 1004
    assert squad.budget == 1029
    assert squad.active_chip == "bboost"
    assert squad.points_on_bench == 7
    starting = [p for p in squad.picks if p.is_starting]
    assert [p.element for p in starting] == [10]


def test_a_missing_squad_raises(tmp_path: Path) -> None:
    """A 200 carrying nothing usable is not a transport failure, so it is not retried."""
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession(routes={"/entry/77/event/": {}}))
    with pytest.raises(FPLAPIError, match="No FPL squad"):
        client.get_squad(77, 2)


def test_history_returns_one_row_per_gameweek_played(client: FPLClient) -> None:
    rows = client.get_history(77)
    assert [(r.event, r.transfers_made, r.transfers_cost) for r in rows] == [(1, 0, 0), (2, 2, 4)]


# ── fixtures ────────────────────────────────────────────────────────────


def test_fixtures_resolve_both_clubs_and_both_difficulties(client: FPLClient) -> None:
    fixture = client.get_fixtures(3)[0]
    assert (fixture.home, fixture.away) == ("ARS", "MCI")
    assert fixture.opponent_of("ARS") == ("MCI", 4, True)
    assert fixture.opponent_of("MCI") == ("ARS", 2, False)
    assert fixture.opponent_of("LIV") is None


def test_a_fixture_without_a_gameweek_or_kickoff_is_kept(client: FPLClient) -> None:
    """A postponed match has neither, and dropping it would hide a blank."""
    unscheduled = client.get_fixtures(3)[1]
    assert unscheduled.event is None
    assert unscheduled.kickoff is None


# ── free transfers ──────────────────────────────────────────────────────


def test_one_free_transfer_in_the_opening_gameweek() -> None:
    assert free_transfers([], upcoming=1) == 1


def test_an_unused_transfer_rolls_over() -> None:
    history = [GameweekResult(event=1, points=60, transfers_made=0, transfers_cost=0)]
    assert free_transfers(history, upcoming=2) == 2


def test_using_the_allowance_resets_it_to_one() -> None:
    history = [GameweekResult(event=1, points=60, transfers_made=1, transfers_cost=0)]
    assert free_transfers(history, upcoming=2) == 1


def test_rollover_is_capped() -> None:
    """Five is the ceiling however long a manager sits on their hands."""
    history = [GameweekResult(event=e, points=0, transfers_made=0, transfers_cost=0) for e in range(1, 12)]
    assert free_transfers(history, upcoming=12) == MAX_FREE_TRANSFERS


def test_a_gameweek_of_hits_never_drops_below_one() -> None:
    history = [GameweekResult(event=1, points=40, transfers_made=4, transfers_cost=12)]
    assert free_transfers(history, upcoming=2) == 1


def test_a_missing_gameweek_is_skipped_rather_than_assumed() -> None:
    """A manager who joined late has no row for the gameweeks before they started."""
    history = [GameweekResult(event=3, points=60, transfers_made=0, transfers_cost=0)]
    assert free_transfers(history, upcoming=4) == 2


# ── retry classification ────────────────────────────────────────────────


def test_rate_limiting_is_retried_but_a_missing_entry_is_not() -> None:
    """A 404 is an entry id that does not exist, and will not start existing."""
    from thefrontoffice.adapters.outbound.platforms.fpl.client import _is_retryable

    def http(status: int) -> requests.exceptions.HTTPError:
        response = requests.Response()
        response.status_code = status
        return requests.exceptions.HTTPError(response=response)

    assert _is_retryable(http(429))
    assert _is_retryable(http(503))
    assert not _is_retryable(http(404))


# ── how a standing reads ────────────────────────────────────────────────


def test_a_classic_standing_is_a_position_in_a_field() -> None:
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="Work", rank=3, is_private=True, rank_count=12)
    assert league.standing == "3 of 12"


def test_a_head_to_head_standing_is_a_placing() -> None:
    """There is no field to be a position in — it is a table of match records."""
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="Hood h2h", rank=1, is_private=True, is_h2h=True)
    assert league.standing == "1st · head-to-head"


@pytest.mark.parametrize(
    ("rank", "expected"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"), (21, "21st")],
)
def test_placings_read_as_english(rank: int, expected: str) -> None:
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="x", rank=rank, is_private=True, is_h2h=True)
    assert league.standing.startswith(expected)


def test_a_missing_field_size_does_not_render_as_zero() -> None:
    """`1 of 0` is worse than saying nothing about the field."""
    from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague

    league = MiniLeague(id=1, name="x", rank=4200, is_private=True, rank_count=None)
    assert league.standing == "4,200"


# ── the league beyond this gameweek ─────────────────────────────────────

H2H_SEASON = {
    "results": [
        {
            "event": 1,
            "entry_1_entry": 7,
            "entry_1_name": "Mine",
            "entry_1_points": 60,
            "entry_2_entry": 99,
            "entry_2_name": "Rival",
            "entry_2_points": 44,
        },
        {
            "event": 2,
            "entry_1_entry": 99,
            "entry_1_name": "Rival",
            "entry_1_points": 51,
            "entry_2_entry": 7,
            "entry_2_name": "Mine",
            "entry_2_points": 70,
        },
        # A tie between two other managers, and one with no gameweek yet.
        {"event": 3, "entry_1_entry": 98, "entry_2_entry": 97},
        {"event": None, "entry_1_entry": 7, "entry_2_entry": 99},
    ]
}


def test_the_whole_h2h_season_comes_back_keyed_by_gameweek(tmp_path: Path) -> None:
    """One request rather than one per gameweek."""
    session = FakeSession({"/leagues-h2h-matches/league/950/": H2H_SEASON})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    season = client.get_h2h_season(950, 7)

    assert sorted(season) == [1, 2]
    assert season[1].opponent_name == "Rival"
    assert (season[1].my_points, season[1].opponent_points) == (60, 44)


def test_the_side_of_a_tie_is_read_from_whichever_slot_you_are_in(tmp_path: Path) -> None:
    """FPL puts an entry in slot 1 or slot 2 with no regard for who is asking."""
    session = FakeSession({"/leagues-h2h-matches/league/950/": H2H_SEASON})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    season = client.get_h2h_season(950, 7)

    assert (season[2].my_points, season[2].opponent_points) == (70, 51)


STANDINGS = {
    "standings": {
        "results": [
            {
                "rank": 1,
                "entry": 99,
                "entry_name": "Rival",
                "player_name": "A Rival",
                "total": 6,
                "matches_played": 2,
                "matches_won": 2,
                "points_for": 104,
            },
            {"rank": 2, "entry": 7, "entry_name": "Mine", "player_name": "Me", "total": 3},
        ]
    }
}


def test_the_two_league_formats_are_different_endpoints(tmp_path: Path) -> None:
    session = FakeSession({"/standings/": STANDINGS})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    client.get_standings(950, is_h2h=True)
    client.get_standings(900, is_h2h=False)

    assert "leagues-h2h/950" in session.requests[0]
    assert "leagues-classic/900" in session.requests[1]


def test_a_table_row_has_a_record_only_once_something_is_played(tmp_path: Path) -> None:
    """A classic league has no results to have a record of."""
    session = FakeSession({"/standings/": STANDINGS})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    rows = client.get_standings(950, is_h2h=True)

    assert rows[0].record == "2W 0D 0L"
    assert rows[1].record == ""


# ── chips ───────────────────────────────────────────────────────────────

CHIPS_BOOTSTRAP = {
    "chips": [
        {"name": "wildcard", "number": 1, "start_event": 2, "stop_event": 19, "chip_type": "transfer"},
        {"name": "bboost", "number": 1, "start_event": 1, "stop_event": 19, "chip_type": "team"},
        # No name at all: nothing that can be shown or decided about.
        {"number": 1, "start_event": 1, "stop_event": 19},
    ],
    # The guard on `_get_bootstrap` refuses a payload with no players, which
    # is what an FPL outage looks like — so a fixture needs one.
    "elements": [{"id": 1, "web_name": "Someone", "element_type": 3, "team": 1}],
    "teams": [{"id": 1, "short_name": "ARS"}],
    "events": [],
}


def test_the_chip_schedule_comes_off_the_bootstrap_everything_else_reads(tmp_path: Path) -> None:
    """So it costs no extra request."""
    session = FakeSession({"/bootstrap-static/": CHIPS_BOOTSTRAP})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    chips = client.get_chips()

    assert [(c.name, c.start_event, c.stop_event) for c in chips] == [("wildcard", 2, 19), ("bboost", 1, 19)]
    assert len([r for r in session.requests if "bootstrap" in r]) == 1


def test_a_chip_carries_the_word_a_manager_uses_for_it() -> None:
    from thefrontoffice.adapters.outbound.platforms.fpl.types import Chip

    assert Chip(name="3xc", start_event=1, stop_event=19).label == "Triple Captain"
    assert Chip(name="bboost", start_event=1, stop_event=19).label == "Bench Boost"


def test_a_chip_knows_which_weeks_it_covers() -> None:
    from thefrontoffice.adapters.outbound.platforms.fpl.types import Chip

    wildcard = Chip(name="wildcard", start_event=2, stop_event=19)

    assert not wildcard.covers(1)
    assert wildcard.covers(2) and wildcard.covers(19)
    assert not wildcard.covers(20)


def test_an_unnamed_chip_is_skipped_rather_than_shown_blank(tmp_path: Path) -> None:
    session = FakeSession({"/bootstrap-static/": CHIPS_BOOTSTRAP})
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=session)

    assert all(c.name for c in client.get_chips())


def test_chips_played_come_back_with_the_week_they_went(tmp_path: Path) -> None:
    history = {"current": [], "chips": [{"name": "bboost", "time": "2026-01-01T00:00:00Z", "event": 3}]}
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession({"/history/": history}))

    played = client.get_chips_played(7)

    assert [(c.name, c.event) for c in played] == [("bboost", 3)]


def test_a_manager_who_has_played_none_has_none(tmp_path: Path) -> None:
    client = FPLClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession({"/history/": {"current": []}}))

    assert client.get_chips_played(7) == []
