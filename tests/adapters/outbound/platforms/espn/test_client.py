"""Tests for ESPN's news feeds: `platforms/espn/client.py`."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from support.http import FakeSession

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import NFL

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
    return ESPNClient(cache=JsonDiskCache(tmp_path / "cache"), session=session), session


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


def test_rows_missing_a_headline_or_a_readable_date_are_skipped(tmp_path: Path) -> None:
    client, _ = _client({"/teams": TEAMS, "team=20": NYJ_NEWS}, tmp_path)

    assert len(client.get_team_news(NFL, ["NYJ"])["NYJ"]) == 2


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


def _event(home: str, away: str, state: str, period: int = 0, clock: float = 0.0, label: str = "") -> dict[str, Any]:
    return {
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}},
                ]
            }
        ],
        "status": {"period": period, "clock": clock, "type": {"state": state, "shortDetail": label}},
    }


def test_the_scoreboard_says_where_each_game_is(tmp_path: Path) -> None:
    board = {"events": [_event("DET", "GB", "in", 3, 782.0, "13:02 - 3rd"), {"competitions": []}]}
    client, session = _client({"/scoreboard": board}, tmp_path)

    [game] = client.get_scoreboard(NFL, "2026", 7)

    assert (game.home, game.away, game.state, game.period, game.clock, game.label) == (
        "DET",
        "GB",
        "in",
        3,
        782.0,
        "13:02 - 3rd",
    )
    assert any("week=7" in url for url in session.requests)


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
