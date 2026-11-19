"""Tests for the Fantasy Premier League client.

FPL is public and read-only, so there is nothing to authenticate — only the
HTTP session and the disk cache stand in.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from support.http import NO_WAIT, FakeSession

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.client import BASE_URL, FPLClient
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import LiveStat, Opponent

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
    "teams": [{"id": 1, "short_name": "ARS", "name": "Arsenal"}, {"id": 2, "short_name": "MCI", "name": "Man City"}],
    "elements": [
        {
            "id": 10,
            "web_name": "Saka",
            "first_name": "Bukayo",
            "second_name": "Saka",
            "element_type": 3,
            "team": 1,
            "now_cost": 95,
            "cost_change_start": 5,
            "ep_next": "6.4",
            "ep_this": "5.1",
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
        "started": True,
        "finished": False,
    },
    {"event": None, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 5, "kickoff_time": None},
    {
        "event": 3,
        "team_h": 2,
        "team_a": 1,
        "team_h_difficulty": 3,
        "team_a_difficulty": 3,
        "kickoff_time": "2026-08-22T14:00:00Z",
        "started": True,
        "finished_provisional": True,
        "finished": False,
    },
]

TRANSFERS = [
    {
        "element_in": 10,
        "element_in_cost": 92,
        "element_out": 11,
        "element_out_cost": 150,
        "entry": 77,
        "event": 2,
        "time": "2026-08-20T19:45:16.885751Z",
    },
    {"element_in": 10, "element_out": 11, "event": None, "time": "2026-08-20T19:45:16Z"},
]

ROUTES = {
    "bootstrap-static": BOOTSTRAP,
    "/entry/77/event/": PICKS,
    "/entry/77/history/": HISTORY,
    "/entry/77/transfers/": TRANSFERS,
    "/entry/77/": ENTRY,
    "/fixtures/": FIXTURES,
}


@pytest.fixture
def client(tmp_path: Path) -> FPLClient:
    return FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession(ROUTES))


# ── the bootstrap payload ───────────────────────────────────────────────


def test_clubs_are_keyed_by_the_abbreviation_a_player_carries(client: FPLClient) -> None:
    assert sorted(client.get_clubs()) == ["ARS", "MCI"]


def test_a_club_the_bootstrap_does_not_list_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """A player of club 9 in a payload listing clubs 1 and 2 is a payload this client does not understand."""
    stray = {**BOOTSTRAP, "elements": [{**BOOTSTRAP["elements"][0], "team": 9}]}
    client = FPLClient(
        cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"bootstrap-static": stray})
    )

    with pytest.raises(FPLAPIError):
        client.get_players()


def test_the_bootstrap_is_fetched_once_per_instance(tmp_path: Path) -> None:
    """A report reads it five times; re-parsing a megabyte each time is waste."""
    session = FakeSession(ROUTES)
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)
    client.get_clubs()
    client.get_players()
    client.get_gameweeks()
    assert sum("bootstrap" in url for url in session.requests) == 1


def test_an_empty_bootstrap_raises(tmp_path: Path) -> None:
    """A 200 carrying nothing usable is not a transport failure, so it is not retried."""
    client = FPLClient(
        cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"bootstrap-static": {}})
    )
    with pytest.raises(FPLAPIError):
        client.get_players()


def test_players_carry_the_games_own_projection(client: FPLClient) -> None:
    saka = client.get_players()[10]
    assert saka.position == "MID"
    assert saka.team == "ARS"
    assert saka.expected_points == 6.4
    assert saka.expected_this == 5.1
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
    assert not second.is_current and second.average_score == 51


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
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"/entry/77/": {}}))
    with pytest.raises(FPLAPIError):
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
    client = FPLClient(
        cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"/entry/77/event/": {}})
    )
    with pytest.raises(FPLAPIError):
        client.get_squad(77, 2)


def test_history_returns_one_row_per_gameweek_played(client: FPLClient) -> None:
    rows = client.get_history(77)
    assert [(r.event, r.transfers_made, r.transfers_cost) for r in rows] == [(1, 0, 0), (2, 2, 4)]


# ── fixtures ────────────────────────────────────────────────────────────


def test_fixtures_resolve_both_clubs_and_both_difficulties(client: FPLClient) -> None:
    fixture = client.get_fixtures(3)[0]
    assert (fixture.home, fixture.away) == ("ARS", "MCI")
    assert fixture.opponent_of("ARS") == Opponent(club="MCI", difficulty=4, home=True, started=True)
    assert fixture.opponent_of("MCI") == Opponent(club="ARS", difficulty=2, home=False, started=True)
    assert fixture.opponent_of("LIV") is None


def test_a_fixture_without_a_gameweek_or_kickoff_is_kept(client: FPLClient) -> None:
    """A postponed match has neither, and dropping it would hide a blank."""
    unscheduled = client.get_fixtures(3)[1]
    assert unscheduled.event is None
    assert unscheduled.kickoff is None
    assert not unscheduled.started and not unscheduled.finished


def test_a_match_is_over_at_the_whistle_not_once_its_bonus_is_confirmed(client: FPLClient) -> None:
    """The game confirms bonus days later; a match long over must not read as still being played."""
    assert client.get_fixtures(3)[2].finished


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
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    season = client.get_h2h_season(950, 7)

    assert sorted(season) == [1, 2]
    assert season[1].opponent_name == "Rival"
    assert (season[1].my_points, season[1].opponent_points) == (60, 44)


def test_one_weeks_tie_is_read_from_your_side(tmp_path: Path) -> None:
    session = FakeSession({"/leagues-h2h-matches/league/950/": {"results": [H2H_SEASON["results"][1]]}})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    tie = client.get_h2h_match(950, 7, 2)

    assert tie is not None
    assert (tie.opponent_entry, tie.my_points, tie.opponent_points) == (99, 70, 51)


def test_a_week_you_are_not_drawn_in_has_no_tie(tmp_path: Path) -> None:
    session = FakeSession({"/leagues-h2h-matches/league/950/": {"results": [H2H_SEASON["results"][2]]}})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    assert client.get_h2h_match(950, 7, 3) is None


def test_the_side_of_a_tie_is_read_from_whichever_slot_you_are_in(tmp_path: Path) -> None:
    """FPL puts an entry in slot 1 or slot 2 with no regard for who is asking."""
    session = FakeSession({"/leagues-h2h-matches/league/950/": H2H_SEASON})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

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
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    client.get_standings(950, is_h2h=True)
    client.get_standings(900, is_h2h=False)

    assert "leagues-h2h/950" in session.requests[0]
    assert "leagues-classic/900" in session.requests[1]


def test_a_table_row_has_a_record_only_once_something_is_played(tmp_path: Path) -> None:
    """A classic league has no results to have a record of."""
    session = FakeSession({"/standings/": STANDINGS})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

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
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

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


def test_chips_played_come_back_with_the_week_they_went(tmp_path: Path) -> None:
    history = {"current": [], "chips": [{"name": "bboost", "time": "2026-01-01T00:00:00Z", "event": 3}]}
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"/history/": history}))

    played = client.get_chips_played(7)

    assert [(c.name, c.event) for c in played] == [("bboost", 3)]


def test_a_manager_who_has_played_none_has_none(tmp_path: Path) -> None:
    client = FPLClient(
        cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession({"/history/": {"current": []}})
    )

    assert client.get_chips_played(7) == []


# ── transfers and what they cost ────────────────────────────────────────


def test_a_transfer_carries_its_purchase_price_and_aware_time(client: FPLClient) -> None:
    [transfer] = client.get_transfers(77)

    assert (transfer.element_in, transfer.element_in_cost, transfer.element_out, transfer.event) == (10, 92, 11, 2)
    assert transfer.time.tzinfo is not None and transfer.time.date().isoformat() == "2026-08-20"


def test_a_player_carries_his_opening_price_where_the_catalog_says(client: FPLClient) -> None:
    players = client.get_players()

    assert players[10].start_cost == 90  # £9.5m now, up £0.5m on the season
    assert players[11].start_cost is None


# ── a player's own page, and the season's fixtures ──────────────────────

SUMMARY = {
    "fixtures": [{"event": 3, "team_h": 1, "team_a": 2, "is_home": True, "difficulty": 4}],
    "history": [
        {
            "round": 1,
            "opponent_team": 2,
            "was_home": False,
            "total_points": 12,
            "minutes": 90,
            "goals_scored": 1,
            "assists": 1,
            "defensive_contribution": 4,
            "expected_goals": "0.81",
            "bps": 40,
        },
        {"round": 2, "opponent_team": 2, "was_home": True, "total_points": 0, "minutes": 0},
    ],
    "history_past": [
        {
            "season_name": "2025/26",
            "total_points": 209,
            "minutes": 2750,
            "starts": 30,
            "goals_scored": 3,
            "assists": 5,
            "clean_sheets": 18,
            "goals_conceded": 20,
            "saves": 0,
            "bonus": 30,
            "expected_goals": "2.94",
            "expected_assists": "1.75",
            "start_cost": 60,
            "end_cost": 73,
            "defensive_contribution": 277,
        }
    ],
}


def test_a_players_page_reads_his_season_match_by_match_and_the_seasons_before(tmp_path: Path) -> None:
    session = FakeSession({**ROUTES, "/element-summary/10/": SUMMARY})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    summary = client.get_player_summaries([10]).value(10)

    first, missed = summary.games
    assert (first.event, first.opponent, first.home, first.points, first.goals, first.assists) == (
        1,
        "MCI",
        False,
        12,
        1,
        1,
    )
    assert (first.defensive_contribution, first.expected_goals) == (4, 0.81)
    assert not missed.played  # a nought with no minutes is a match missed
    assert [(s.season, s.defensive_contribution, s.end_cost) for s in summary.past] == [("2025/26", 277, 73)]


def test_several_players_pages_are_fetched_once_each_and_kept(tmp_path: Path) -> None:
    session = FakeSession({**ROUTES, "/element-summary/10/": SUMMARY, "/element-summary/11/": SUMMARY})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    assert set(client.get_player_summaries([10, 11, 10]).values) == {10, 11}
    client.get_player_summaries([10, 11])
    assert sum("element-summary" in url for url in session.requests) == 2


def test_a_page_that_will_not_load_is_reported_as_missing_not_empty(tmp_path: Path) -> None:
    """A player with no log yet and a player whose log failed are different answers."""
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=FakeSession(ROUTES))

    batch = client.get_player_summaries([10])
    with pytest.raises(FPLAPIError):
        batch.value(10)


def test_the_seasons_fixtures_come_in_one_request(tmp_path: Path) -> None:
    heavy = [{**f, "stats": [{"identifier": "goals_scored", "a": [], "h": []}]} for f in FIXTURES]
    session = FakeSession({**ROUTES, "/fixtures/": heavy})
    client = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session)

    fixtures = client.get_season_fixtures()

    assert [(f.event, f.home, f.away) for f in fixtures] == [(3, "ARS", "MCI"), (None, "MCI", "ARS"), (3, "MCI", "ARS")]
    assert [url for url in session.requests if "fixtures" in url] == [f"{BASE_URL}/fixtures/"]


def test_a_player_carries_his_news_time_defensive_contribution_and_price_pressure(tmp_path: Path) -> None:
    saka = {
        **BOOTSTRAP["elements"][0],
        "news_added": "2026-11-16T19:00:05.154377Z",
        "defensive_contribution": 91,
        "defensive_contribution_per_90": "9.1",
        "price_change_percent": "96.8",
        "price_change_projections": [
            {"offset": 1, "projected_percent": "98.3", "likelihood": 4},
            {"offset": 0, "projected_percent": "102.3", "likelihood": 5},
        ],
        "price_change_locked_until": "2026-11-21T18:35:54Z",
    }
    session = FakeSession({**ROUTES, "bootstrap-static": {**BOOTSTRAP, "elements": [saka]}})
    player = FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session).get_players()[10]

    assert player.news_added == datetime(2026, 11, 16, 19, 0, 5, 154377, tzinfo=UTC)
    assert (player.defensive_contribution, player.defensive_contribution_per_90) == (91, 9.1)
    assert (player.price_progress, player.price_tonight) == (96.8, 102.3)
    assert player.price_locked_until == datetime(2026, 11, 21, 18, 35, 54, tzinfo=UTC)


def test_a_player_with_no_news_or_projection_carries_none(client: FPLClient) -> None:
    player = client.get_players()[11]
    assert player.news_added is None
    assert player.price_tonight is None
    assert player.price_locked_until is None


# ── results ─────────────────────────────────────────────────────────────

LIVE_GW1 = {
    "elements": [
        {
            "id": 10,
            "stats": {"total_points": 8, "minutes": 90, "bonus": 1, "influence": "40.2"},
            "explain": [
                {
                    "fixture": 1,
                    "stats": [
                        {"identifier": "minutes", "points": 2, "value": 90},
                        {"identifier": "defensive_contribution", "points": 2, "value": 11},
                    ],
                },
                {"fixture": 2, "stats": [{"identifier": "minutes", "points": 2, "value": 90}]},
            ],
        },
        {"id": 11, "stats": {"total_points": 0, "minutes": 0}, "explain": []},
        {"stats": {"total_points": 3}},
    ]
}


def _live_client(tmp_path: Path) -> tuple[FPLClient, FakeSession]:
    session = FakeSession({"/event/1/live/": LIVE_GW1})
    return FPLClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session), session


def test_results_read_each_players_points_minutes_matches_and_defensive_contributions(tmp_path: Path) -> None:
    client, _ = _live_client(tmp_path)

    week = client.get_results([1])[1]

    assert week[10] == LiveStat(points=8, minutes=90, matches=2, bonus=1, defending=2)
    assert week[11] == LiveStat(points=0, minutes=0, matches=0)
    assert len(week) == 2  # a row without an id is nobody


def test_results_already_kept_are_not_fetched_again(tmp_path: Path) -> None:
    client, session = _live_client(tmp_path)

    assert client.get_results([1]) == client.get_results([1])
    assert len(session.requests) == 1


def test_a_gameweek_whose_results_will_not_load_is_refused_not_read_as_empty(tmp_path: Path) -> None:
    client, _ = _live_client(tmp_path)

    with pytest.raises(FPLAPIError, match="GW2"):
        client.get_results([1, 2])


def test_the_live_feed_counts_a_players_matches_too(tmp_path: Path) -> None:
    client, _ = _live_client(tmp_path)

    assert client.get_live(1)[10].matches == 2
