"""Tests for ESPN's news feeds: `platforms/espn/client.py`."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from support.http import NO_WAIT, FakeSession

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA, NFL, Athlete

TEAMS = {
    "sports": [
        {
            "leagues": [
                {"teams": [{"team": {"id": "2", "abbreviation": "BUF"}}, {"team": {"id": "20", "abbreviation": "NYJ"}}]}
            ]
        }
    ]
}


def _row(headline: str, published: str, athletes: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    return {
        "id": headline,
        "headline": headline,
        "published": published,
        "description": "summary",
        "links": {"web": {"href": f"https://espn.example/{headline}"}},
        "categories": [{"type": "league", "description": "NFL"}]
        + [{"type": "athlete", "description": name} for name in athletes],
        **extra,
    }


NYJ_NEWS = {
    "articles": [
        _row("older", "2026-10-15T12:00:00Z", ("Breece Hall",)),
        _row("newer", "2026-10-20T12:00:00Z"),
        {"headline": "no date"},
        _row("bad date", "yesterday"),
    ]
}


def _client(routes: dict[str, Any], tmp_path: Path) -> tuple[ESPNClient, FakeSession]:
    session = FakeSession(routes)
    return ESPNClient(cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, session=session), session


def test_a_clubs_news_comes_back_newest_first_with_its_tagged_players(tmp_path: Path) -> None:
    client, session = _client({"/teams": TEAMS, "team=20": NYJ_NEWS}, tmp_path)

    news = client.get_team_news(NFL, ["NYJ"])

    assert [a.headline for a in news["NYJ"]] == ["newer", "older"]
    older = news["NYJ"][1]
    assert older.athletes == ["Breece Hall"]
    assert older.published == datetime(2026, 10, 15, 12, tzinfo=UTC)
    assert older.url and older.summary
    # Asked by ESPN's own id for the club, not its abbreviation.
    assert any("team=20" in url for url in session.requests)


def test_a_club_whose_feed_fails_is_left_out_rather_than_failing_the_rest(tmp_path: Path) -> None:
    client, _ = _client({"/teams": TEAMS, "team=20": NYJ_NEWS}, tmp_path)

    news = client.get_team_news(NFL, ["NYJ", "BUF"])

    assert set(news) == {"NYJ"}


def test_a_club_espn_does_not_know_is_not_asked_for(tmp_path: Path) -> None:
    client, session = _client({"/teams": TEAMS}, tmp_path)

    assert client.get_team_news(NFL, ["XXX"]) == {}
    assert not any("team=" in url for url in session.requests)


def test_an_unreadable_club_list_is_an_error_not_an_empty_league(tmp_path: Path) -> None:
    client, _ = _client({"/teams": {"sports": []}}, tmp_path)

    with pytest.raises(ESPNAPIError):
        client.get_team_news(NFL, ["NYJ"])


# ── the scoreboard ──────────────────────────────────────────────────────


def _event(
    home: str,
    away: str,
    state: str,
    period: int = 0,
    clock: float = 0.0,
    label: str = "",
    score: tuple[str, str] | None = None,
    date: str = "",
) -> dict[str, Any]:
    scored = ({"score": score[0]}, {"score": score[1]}) if score else ({}, {})
    return {
        **({"date": date} if date else {}),
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}, **scored[0]},
                    {"homeAway": "away", "team": {"abbreviation": away}, **scored[1]},
                ]
            }
        ],
        "status": {"period": period, "clock": clock, "type": {"state": state, "shortDetail": label}},
    }


def test_the_scoreboard_says_where_each_game_is(tmp_path: Path) -> None:
    board = {
        "events": [
            _event("DET", "GB", "in", 3, 782.0, "13:02 - 3rd", score=("17", "10")),
            _event("NYJ", "NE", "pre", label="Sun 1:00 PM", date="2026-10-25T17:00Z"),
            {"competitions": []},
        ]
    }
    client, session = _client({"/scoreboard": board}, tmp_path)

    game, before = client.get_scoreboard(NFL, "2026", 7)

    assert (game.home, game.away, game.state, game.period, game.clock, game.label) == (
        "DET",
        "GB",
        "in",
        3,
        782.0,
        "13:02 - 3rd",
    )
    assert (game.home_score, game.away_score) == (17, 10)
    # ESPN sends no score before kickoff.
    assert (before.home_score, before.away_score) == (0, 0)
    assert before.kickoff == datetime(2026, 10, 25, 17, tzinfo=UTC)
    assert game.kickoff is None  # ESPN gave no time
    assert any("week=7" in url for url in session.requests)


def test_a_days_scoreboard_is_read_by_its_date(tmp_path: Path) -> None:
    """Basketball plays daily, so its board is asked for by the day rather than the week."""
    board = {"events": [_event("LAL", "BOS", "pre", date="2026-02-12T03:30Z")]}
    client, session = _client({"/scoreboard": board}, tmp_path)

    [game] = client.get_day_scoreboard(NBA, date(2026, 2, 11))

    assert (game.home, game.away, game.kickoff) == ("LAL", "BOS", datetime(2026, 2, 12, 3, 30, tzinfo=UTC))
    assert any("dates=20260211" in url and "week=" not in url for url in session.requests)


def test_an_unreadable_scoreboard_is_an_error(tmp_path: Path) -> None:
    client, _ = _client({"/scoreboard": ["not", "a", "scoreboard"]}, tmp_path)

    with pytest.raises(ESPNAPIError):
        client.get_scoreboard(NFL, "2026", 7)


def _injury(name: str, club: str, status: str, date: str = "2026-10-27T13:11Z") -> dict[str, Any]:
    return {"status": status, "date": date, "athlete": {"displayName": name, "team": {"abbreviation": club}}}


INJURIES = {
    "injuries": [
        {"displayName": "New York Jets", "injuries": [_injury("Breece Hall", "NYJ", "Questionable")]},
        {
            "displayName": "Indianapolis Colts",
            "injuries": [
                _injury("Tyler Warren", "IND", "Out"),
                {"status": "Out", "athlete": {"displayName": "No Date", "team": {"abbreviation": "IND"}}},
                _injury("Bad Date", "IND", "Out", date="soon"),
            ],
        },
    ]
}


def test_the_injury_report_lists_every_clubs_players_with_when_each_was_set(tmp_path: Path) -> None:
    client, _ = _client({"/injuries": INJURIES}, tmp_path)

    reports = client.get_injuries(NFL)

    assert [(r.name, r.club, r.status) for r in reports] == [
        ("Breece Hall", "NYJ", "Questionable"),
        ("Tyler Warren", "IND", "Out"),
    ]
    assert reports[0].updated == datetime(2026, 10, 27, 13, 11, tzinfo=UTC)


def test_an_unreadable_injury_report_is_an_error_not_a_healthy_league(tmp_path: Path) -> None:
    client, _ = _client({"/injuries": ["not", "a", "report"]}, tmp_path)

    with pytest.raises(ESPNAPIError):
        client.get_injuries(NFL)


MINSHEW = {
    "status": "Injured Reserve",
    "date": "2026-11-18T04:40Z",
    "shortComment": "Minshew (elbow) underwent UCL reconstructive surgery Monday.",
    "athlete": {
        "displayName": "Gardner Minshew II",
        "team": {"abbreviation": "ARI"},
        "links": [
            {"rel": ["playercard", "desktop", "athlete"], "href": "https://www.espn.com/nfl/player/_/id/4038524/g"},
            {"rel": ["news", "sportscenter", "app", "athlete"], "href": "sportscenter://x-callback-url/news"},
            {"rel": ["news", "desktop", "athlete"], "href": "https://www.espn.com/nfl/player/news/_/id/4038524/g"},
        ],
    },
    "details": {"type": "Elbow", "location": "Arm", "detail": "Surgery", "side": "Right", "returnDate": "2027-02-15"},
}


def test_an_injury_row_carries_espns_athlete_id_its_return_and_the_latest_word(tmp_path: Path) -> None:
    unspecified = {
        **_injury("Breece Hall", "NYJ", "Questionable"),
        "details": {"type": "Knee", "detail": "Not Specified", "side": "Not Specified", "returnDate": "never"},
    }
    client, _ = _client({"/injuries": {"injuries": [{"injuries": [MINSHEW, unspecified]}]}}, tmp_path)

    minshew, hall = client.get_injuries(NFL)

    assert minshew.athlete_id == "4038524"
    assert minshew.returns == date(2027, 2, 15)
    assert minshew.injury == "Right elbow, surgery"
    assert minshew.comment.startswith("Minshew (elbow)")
    assert minshew.url == "https://www.espn.com/nfl/player/news/_/id/4038524/g"
    # Whatever ESPN leaves unspecified, or dates unreadably, reads as nothing.
    assert (hall.athlete_id, hall.returns, hall.injury, hall.url) == ("", None, "Knee", "")


def _roster(*players: tuple[str, str]) -> dict[str, Any]:
    items: list[Any] = [
        {"id": pid, "fullName": name, "injuries": [], "headshot": {"href": "x"}} for pid, name in players
    ]
    return {
        "team": {"abbreviation": "?"},
        "athletes": [{"position": "offense", "items": [*items, {"id": "9"}]}, "junk"],
    }


def test_every_clubs_roster_names_each_player_with_espns_id_under_espns_abbreviation(tmp_path: Path) -> None:
    routes = {
        "/teams/2/roster": _roster(("1", "Josh Allen"), ("2", "James Cook")),
        "/teams/20/roster": _roster(("3", "Breece Hall")),
        "/teams": TEAMS,
    }
    client, _ = _client(routes, tmp_path)

    roster = client.get_rosters(NFL)

    assert [(a.athlete_id, a.name, a.club) for a in roster] == [
        ("1", "Josh Allen", "BUF"),
        ("2", "James Cook", "BUF"),
        ("3", "Breece Hall", "NYJ"),
    ]


def test_a_club_whose_roster_fails_is_left_out_rather_than_failing_the_rest(tmp_path: Path) -> None:
    client, _ = _client({"/teams/2/roster": _roster(("1", "Josh Allen")), "/teams": TEAMS}, tmp_path)

    assert [a.club for a in client.get_rosters(NFL)] == ["BUF"]


ACHANE = {
    "status": "Injured Reserve",
    "date": "2026-09-28T20:10Z",
    "shortComment": "The Dolphins placed Achane (knee) on injured reserve Monday.",
    "details": {"type": "Knee - ACL", "detail": "Surgery", "side": "Left", "returnDate": "2027-02-15"},
}


def test_an_athletes_own_history_gives_his_newest_entry_with_its_return(tmp_path: Path) -> None:
    history = {
        "count": 3,
        "items": [
            {"status": "Questionable", "date": "2026-09-01T12:00Z"},
            ACHANE,
            {"status": "Out", "date": "unreadable"},
        ],
    }
    routes = {"athletes/4429160/injuries": history, "athletes/1/injuries": {"count": 0, "items": []}}
    client, session = _client(routes, tmp_path)
    athletes = [
        Athlete(athlete_id="4429160", name="De'Von Achane", club="MIA"),
        Athlete(athlete_id="1", name="Never Hurt", club="MIA"),
        Athlete(athlete_id="2", name="Unknown To ESPN", club="MIA"),
    ]

    found = client.get_athlete_injuries(NFL, "2026", athletes)

    assert set(found) == {"4429160"}
    report = found["4429160"]
    assert (report.name, report.club, report.status, report.athlete_id) == (
        "De'Von Achane",
        "MIA",
        "Injured Reserve",
        "4429160",
    )
    assert report.updated == datetime(2026, 9, 28, 20, 10, tzinfo=UTC)
    assert report.returns == date(2027, 2, 15)
    assert report.injury == "Left knee - acl, surgery"
    assert report.comment.startswith("The Dolphins placed Achane")
    assert report.url == "https://www.espn.com/nfl/player/news/_/id/4429160"
    assert any("/leagues/nfl/seasons/2026/athletes/4429160/injuries" in url for url in session.requests)
