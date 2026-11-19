"""Tests for joining ESPN's club news to Sleeper's players: `nfl/news.py`.

Matching, the news window, ordering and how a headline reads are the shared join's,
covered in `competitions/test_news.py`; these cover which of Sleeper's players a club's feed is read for.
"""

from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.news import attach
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)

PLAYERS = {
    "hall": PlayerMeta(player_id="hall", name="Breece Hall", position="RB", team="NYJ"),
    "wilson": PlayerMeta(player_id="wilson", name="Garrett Wilson", position="WR", team="NYJ"),
    "allen": PlayerMeta(player_id="allen", name="Josh Allen", position="QB", team="BUF"),
    "NYJ": PlayerMeta(player_id="NYJ", name="New York Jets", position="DEF", team="NYJ"),
}


def _article(headline: str, summary: str = "") -> NewsArticle:
    return NewsArticle(article_id=headline, published=NOW - timedelta(days=1), headline=headline, summary=summary)


def _ids(news: dict[str, list[NewsArticle]], players: dict[str, PlayerMeta] = PLAYERS) -> dict[str, list[str]]:
    joined = attach(news, players, NOW)
    return {pid: [a.article_id for a in articles] for pid, articles in joined.by_player.items()}


def test_a_player_is_matched_on_his_full_name_in_the_headline_or_summary() -> None:
    news = {"NYJ": [_article("Breece Hall back at practice"), _article("b", summary="Garrett Wilson limited")]}

    assert _ids(news) == {"hall": ["Breece Hall back at practice"], "wilson": ["b"]}


def test_a_surname_alone_is_not_a_match() -> None:
    """'Hall' is a word, a stadium and half the league."""
    assert _ids({"NYJ": [_article("Hall of Fame game moved")]}) == {}


def test_only_a_clubs_own_players_are_read_from_its_feed() -> None:
    """The Jets' feed mentioning Josh Allen is not news filed for him here."""
    assert _ids({"NYJ": [_article("Jets defense gets ready for Josh Allen")]}) == {}


def test_a_team_defense_does_not_inherit_every_article_about_its_club() -> None:
    assert "NYJ" not in _ids({"NYJ": [_article("New York Jets fall to Patriots")]})


def test_washington_is_found_under_espns_abbreviation() -> None:
    commanders = {"mclaurin": PlayerMeta(player_id="mclaurin", name="Terry McLaurin", position="WR", team="WAS")}

    assert espn_club("WAS") != "WAS"
    assert _ids({espn_club("WAS"): [_article("Terry McLaurin returns")]}, commanders) == {
        "mclaurin": ["Terry McLaurin returns"]
    }
