"""Tests for joining ESPN's club news to Sleeper's players: `nfl/news.py`.

Matching, the news window, ordering and how a headline reads are the shared join's,
covered in `competitions/test_news.py`; these cover which of Sleeper's players a club's feed is read for,
and which of its stories are every one of the club's players' news.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.news import NEWS_WINDOW
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.news import PLAY_CALLER, QB_CHANGE, TRADE, attach
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


COLTS = {
    "jones": PlayerMeta(player_id="jones", name="Daniel Jones", position="QB", team="IND", depth_chart_order=1),
    "richardson": PlayerMeta(
        player_id="richardson", name="Anthony Richardson", position="QB", team="IND", depth_chart_order=2
    ),
    "warren": PlayerMeta(player_id="warren", name="Tyler Warren", position="TE", team="IND", depth_chart_order=1),
    "downs": PlayerMeta(player_id="downs", name="Josh Downs", position="WR", team="PIT"),
    "IND": PlayerMeta(player_id="IND", name="Indianapolis Colts", position="DEF", team="IND"),
    "hall": PLAYERS["hall"],
}


def _team(headline: str, summary: str = "", days_ago: float = 1) -> dict[str, list[tuple[str, str]]]:
    """Each player's club stories as (kind, headline), from one article in the Colts' feed."""
    article = NewsArticle(
        article_id=headline, published=NOW - timedelta(days=days_ago), headline=headline, summary=summary
    )
    joined = attach({"IND": [article]}, COLTS, NOW)
    return {pid: [(s.kind, s.article.headline) for s in stories] for pid in COLTS if (stories := joined.team(pid))}


def test_a_backup_quarterback_named_to_start_is_every_colts_players_qb_change() -> None:
    """Tyler Warren's week turns on who throws to him, though the story never names him."""
    found = _team("Colts turn to Anthony Richardson", summary="Richardson will start Sunday.")

    assert found["warren"] == [(QB_CHANGE, "Colts turn to Anthony Richardson")]
    assert found["jones"] == [(QB_CHANGE, "Colts turn to Anthony Richardson")]
    # His own news already: not repeated as his club's.
    assert "richardson" not in found
    # A team defense, and another club's player, are nobody the Colts' feed is read for.
    assert "IND" not in found and "hall" not in found


def test_the_starter_named_to_start_is_no_change() -> None:
    assert _team("Daniel Jones to start despite ankle") == {}


def test_a_benched_starter_is_a_qb_change() -> None:
    assert _team("Colts bench Daniel Jones")["warren"] == [(QB_CHANGE, "Colts bench Daniel Jones")]


def test_talk_of_a_change_is_not_one() -> None:
    assert _team("Could the Colts bench Daniel Jones?") == {}


def test_without_a_listed_starter_nobody_is_a_backup() -> None:
    unlisted = {pid: replace(meta, depth_chart_order=0) for pid, meta in COLTS.items()}
    article = NewsArticle(article_id="1", published=NOW - timedelta(days=1), headline="Anthony Richardson to start")

    assert attach({"IND": [article]}, unlisted, NOW).by_club == {}


def test_a_trade_naming_an_offensive_player_anywhere_in_the_league_is_a_trade() -> None:
    """Josh Downs is a Steeler in Sleeper by the time the Colts' feed reports the deal."""
    assert _team("Colts trade Josh Downs to Pittsburgh")["warren"] == [(TRADE, "Colts trade Josh Downs to Pittsburgh")]


def test_trade_wording_naming_no_offensive_player_is_not_a_trade() -> None:
    assert _team("Colts trade a seventh-round pick for a linebacker") == {}


def test_a_new_play_caller_is_every_players_story() -> None:
    found = _team("Colts fire offensive coordinator")

    assert found["warren"] == [(PLAY_CALLER, "Colts fire offensive coordinator")]


def test_a_club_story_older_than_the_window_is_left_out() -> None:
    assert _team("Colts bench Daniel Jones", days_ago=NEWS_WINDOW.days + 1) == {}


def test_a_question_is_talk_of_a_change_not_one() -> None:
    """A roundup asking after deadline deals names half the league's offense."""
    assert _team("Latest intel", summary="No deal for Josh Downs? Colts seeking a trade.") == {}


def test_the_trade_deadline_alone_is_not_a_trade() -> None:
    assert _team("Josh Downs focused on the Colts with the trade deadline behind him") == {}
