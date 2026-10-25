"""Tests for ESPN's news feeds: `platforms/espn/client.py`."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_fpl_client import FakeSession

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
from thefrontoffice.adapters.outbound.platforms.espn.types import NFL, ScoreboardGame
from thefrontoffice.domain.errors import ESPNAPIError

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


def test_how_much_of_a_game_is_left_follows_its_clock() -> None:
    assert ScoreboardGame("A", "B", "pre").left == 1.0
    assert ScoreboardGame("A", "B", "post").left == 0.0
    assert ScoreboardGame("A", "B", "in", period=2, clock=0.0).left == 0.5  # halftime
    assert ScoreboardGame("A", "B", "in", period=4, clock=450.0).left == 0.125
    assert ScoreboardGame("A", "B", "in", period=5, clock=360.0).left == 0.1  # six minutes of overtime
