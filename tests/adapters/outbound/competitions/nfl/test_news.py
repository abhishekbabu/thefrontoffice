"""Tests for joining ESPN's club news to Sleeper's players: `nfl/news.py`."""

from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.nfl.news import NEWS_WINDOW, attach, espn_club
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)

PLAYERS = {
    "hall": PlayerMeta(player_id="hall", name="Breece Hall", position="RB", team="NYJ"),
    "wilson": PlayerMeta(player_id="wilson", name="Garrett Wilson", position="WR", team="NYJ"),
    "allen": PlayerMeta(player_id="allen", name="Josh Allen", position="QB", team="BUF"),
    "NYJ": PlayerMeta(player_id="NYJ", name="New York Jets", position="DEF", team="NYJ"),
}


def _article(headline: str, days_ago: float = 1, athletes: tuple[str, ...] = (), summary: str = "") -> NewsArticle:
    return NewsArticle(
        article_id=headline,
        published=NOW - timedelta(days=days_ago),
        headline=headline,
        summary=summary,
        athletes=list(athletes),
    )


def _ids(news: dict[str, list[NewsArticle]], players: dict[str, PlayerMeta] = PLAYERS) -> dict[str, list[str]]:
    joined = attach(news, players, NOW)
    return {pid: [a.article_id for a in articles] for pid, articles in joined.by_player.items()}


def test_a_player_is_matched_on_espns_tag() -> None:
    assert _ids({"NYJ": [_article("a", athletes=("Breece Hall",))]}) == {"hall": ["a"]}


def test_a_player_is_matched_on_his_full_name_in_the_headline_or_summary() -> None:
    news = {"NYJ": [_article("Breece Hall back at practice"), _article("b", summary="Garrett Wilson limited")]}

    assert _ids(news) == {"hall": ["Breece Hall back at practice"], "wilson": ["b"]}


def test_a_surname_alone_is_not_a_match() -> None:
    """'Hall' is a word, a stadium and half the league."""
    assert _ids({"NYJ": [_article("Hall of Fame game moved")]}) == {}


def test_only_a_clubs_own_players_are_read_from_its_feed() -> None:
    """The Jets' feed mentioning Josh Allen is not news filed for him here."""
    assert _ids({"NYJ": [_article("Jets defense gets ready for Josh Allen")]}) == {}


def test_two_players_of_one_name_on_one_club_match_nothing() -> None:
    twins = {
        **PLAYERS,
        "hall2": PlayerMeta(player_id="hall2", name="Breece Hall", position="WR", team="NYJ"),
    }

    assert "hall" not in _ids({"NYJ": [_article("Breece Hall scores")]}, twins)


def test_a_team_defense_does_not_inherit_every_article_about_its_club() -> None:
    assert "NYJ" not in _ids({"NYJ": [_article("New York Jets fall to Patriots")]})


def test_news_older_than_the_window_is_dropped() -> None:
    stale = (NEWS_WINDOW + timedelta(days=1)).days

    assert _ids({"NYJ": [_article("Breece Hall", days_ago=stale)]}) == {}


def test_a_players_news_is_newest_first() -> None:
    news = {
        "NYJ": [
            _article("old", days_ago=5, athletes=("Breece Hall",)),
            _article("new", days_ago=1, athletes=("Breece Hall",)),
        ]
    }

    assert _ids(news)["hall"] == ["new", "old"]


def test_washington_is_found_under_espns_abbreviation() -> None:
    commanders = {"mclaurin": PlayerMeta(player_id="mclaurin", name="Terry McLaurin", position="WR", team="WAS")}

    assert espn_club("WAS") != "WAS"
    assert _ids({espn_club("WAS"): [_article("Terry McLaurin returns")]}, commanders) == {
        "mclaurin": ["Terry McLaurin returns"]
    }


def test_the_drawer_lines_are_dated_and_carry_the_headline() -> None:
    joined = attach({"NYJ": [_article("Breece Hall returns", days_ago=0)]}, PLAYERS, NOW)

    [line] = joined.stats("hall")
    assert line.value == "Breece Hall returns"
    assert line.label == "Thu 22 Oct"
