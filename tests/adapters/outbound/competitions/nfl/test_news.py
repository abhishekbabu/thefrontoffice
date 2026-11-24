"""Tests for joining ESPN's club news to Sleeper's players: `nfl/news.py`.

Matching, the news window, ordering and how a headline reads are the shared join's,
covered in `competitions/test_news.py`; these cover which of Sleeper's players a club's feed is read for,
and which of its stories are every one of the club's players' news.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from thefrontoffice.adapters.outbound.competitions.news import NEWS_WINDOW, ClubStory
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
    joined = attach(news, players, NOW, {})
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
    joined = attach({"IND": [article]}, COLTS, NOW, {})
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

    assert attach({"IND": [article]}, unlisted, NOW, {}).by_club == {}


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


# Week 12, 2026: the Colts cut Daniel Jones on Fri 20 Nov and started Anthony Richardson. By the time
# the app read it, Sleeper had Jones a free agent and Richardson atop the depth chart.
CUT = NewsArticle(
    article_id="cut",
    published=NOW - timedelta(days=2),
    headline="Colts cut QB Daniel Jones, turn to Anthony Richardson Sr. for next start",
    summary="The Colts have cut quarterback Daniel Jones and are turning to Anthony Richardson Sr. to start.",
)
STICKING = NewsArticle(
    article_id="sticking",
    published=NOW - timedelta(days=6),
    headline="Colts sticking with Daniel Jones at QB despite dreadful start",
    athletes=["Daniel Jones"],
)
AFTER_THE_CUT = {
    **COLTS,
    "jones": replace(COLTS["jones"], team="FA", depth_chart_order=0),
    "richardson": replace(COLTS["richardson"], depth_chart_order=1),
}


def _kinds(articles: list[NewsArticle], players: dict[str, PlayerMeta]) -> list[tuple[str, str]]:
    """Tyler Warren's club stories as (kind, article id)."""
    return [(s.kind, s.article.article_id) for s in attach({"IND": articles}, players, NOW, {}).team("warren")]


def test_the_colts_cutting_their_starter_reaches_tyler_warren_once_sleeper_has_moved_both_quarterbacks() -> None:
    assert _kinds([CUT, STICKING], AFTER_THE_CUT) == [(QB_CHANGE, "cut")]


def test_the_colts_cutting_their_starter_reaches_tyler_warren_before_sleeper_has_moved_either() -> None:
    assert _kinds([CUT], COLTS) == [(QB_CHANGE, "cut")]


def test_a_released_quarterback_named_alone_is_his_old_clubs_qb_change() -> None:
    released = replace(CUT, headline="Colts release Daniel Jones", summary="")

    assert _kinds([released], AFTER_THE_CUT) == [(QB_CHANGE, "cut")]


def test_trading_away_only_a_quarterback_is_a_qb_change() -> None:
    traded = replace(CUT, headline="Colts trade Daniel Jones for a pick", summary="")

    assert _kinds([traded], COLTS) == [(QB_CHANGE, "cut")]


def test_a_clubs_start_to_the_season_is_not_a_backup_starting() -> None:
    assert _team("Anthony Richardson upbeat about Colts despite 3-7 start") == {}


def test_a_trade_that_only_mentions_the_quarterback_does_not_move_him() -> None:
    """Three defenders traded for, and the starter's reaction: no quarterback changed hands."""
    assert _team("Daniel Jones sees a shot as the Colts add three defenders in trades") == {}


@pytest.mark.parametrize(
    "headline",
    [
        "Colts part ways with Daniel Jones",
        "Colts move on from QB Daniel Jones",
        "Colts bench Daniel Jones for Anthony Richardson",
        "Anthony Richardson to start Sunday for Colts",
        "Colts turning to Anthony Richardson",
        "Colts elevate Anthony Richardson to starter",
        "Colts name Anthony Richardson the starter",
        "Daniel Jones out for the season with torn Achilles",
        "Daniel Jones released by Colts",
        "Daniel Jones traded to Minnesota",
        "Colts acquire QB Anthony Richardson",
        "Deal sends Daniel Jones to Minnesota",
    ],
)
def test_each_way_a_story_says_the_quarterback_changed(headline: str) -> None:
    assert _team(headline)["warren"] == [(QB_CHANGE, headline)]


@pytest.mark.parametrize(
    "headline",
    [
        # Each new phrase, said of something other than the club's quarterback.
        "Colts part ways with defensive coordinator",
        "Daniel Jones says Colts will move on from loss",
        "Colts elevate Anthony Richardson from practice squad",
        "Colts name Daniel Jones a team captain",
        "Anthony Richardson out for the season with knee injury",
        "Daniel Jones traded barbs with Texans",
        "Colts acquire linebacker, Daniel Jones approves",
        "Deal sends a Colts linebacker to Minnesota, Daniel Jones reacts",
        "Daniel Jones is turning to film to fix his mechanics",
    ],
)
def test_the_same_words_about_anyone_else_are_no_qb_change(headline: str) -> None:
    assert QB_CHANGE not in {kind for stories in _team(headline).values() for kind, _ in stories}


def test_a_trade_counts_where_its_player_is_the_object_however_it_is_put() -> None:
    for headline in (
        "Josh Downs traded to Pittsburgh",
        "Steelers acquire Josh Downs",
        "Deal sends Josh Downs to Pittsburgh",
    ):
        assert _team(headline)["warren"] == [(TRADE, headline)]
    # Mentioned beside a trade of others is not traded.
    assert _team("Colts add three linebackers in trades, Josh Downs says") == {}


def test_a_depth_chart_change_is_kept_only_where_no_story_reports_one() -> None:
    depth = ClubStory(
        kind=QB_CHANGE,
        article=NewsArticle(article_id="depth", published=NOW - timedelta(days=1), headline="Depth chart"),
    )
    told = NewsArticle(article_id="told", published=NOW - timedelta(days=2), headline="Colts bench Daniel Jones")

    assert [s.article.article_id for s in attach({"IND": [told]}, COLTS, NOW, {"IND": depth}).team("warren")] == [
        "told"
    ]
    assert [s.article.article_id for s in attach({}, COLTS, NOW, {"IND": depth}).team("warren")] == ["depth"]


def _qb(pid: str, name: str, team: str, depth: int, status: str = "") -> PlayerMeta:
    return PlayerMeta(player_id=pid, name=name, position="QB", team=team, depth_chart_order=depth, injury_status=status)


def _club_kinds(club: str, quarterbacks: list[PlayerMeta], headline: str, summary: str = "") -> list[str]:
    """A receiver's club stories, by kind, from one article in his club's feed, beside these quarterbacks."""
    players = {q.player_id: q for q in quarterbacks}
    players["wr"] = PlayerMeta(player_id="wr", name="A Receiver", position="WR", team=club, depth_chart_order=1)
    article = NewsArticle(article_id=headline, published=NOW - timedelta(days=1), headline=headline, summary=summary)
    return [s.kind for s in attach({club: [article]}, players, NOW, {}).team("wr")]


# Week 12, 2026: each of these was read as a quarterback change, and none was one.
SEAHAWKS = [_qb("darnold", "Sam Darnold", "SEA", 1, "Out"), _qb("lock", "Drew Lock", "SEA", 2)]


def test_a_game_recap_naming_the_backup_who_played_is_no_qb_change() -> None:
    """The start in its summary is the other club's quarterback's."""
    assert (
        _club_kinds(
            "SEA",
            SEAHAWKS,
            "Seahawks beat Raiders 21-13 as Drew Lock throws for 2 TDs and Seattle sacks Fernando Mendoza 6 times",
            "The lead-up was almost all about Fernando Mendoza, at last receiving his first start as the Raiders' QB.",
        )
        == []
    )


def test_a_starter_replaced_in_a_game_is_no_change_once_he_is_listed_first_and_fit_again() -> None:
    headline = "Jets QB Geno Smith suffers ankle injury, replaced by rookie Cade Klubnik"
    jets = [_qb("smith", "Geno Smith", "NYJ", 1), _qb("klubnik", "Cade Klubnik", "NYJ", 3)]

    assert _club_kinds("NYJ", jets, headline) == []
    # While he is still out, the replacement is the change.
    assert _club_kinds("NYJ", [replace(jets[0], injury_status="Out"), jets[1]], headline) == [QB_CHANGE]


def test_a_starter_returning_to_his_own_job_is_no_qb_change() -> None:
    browns = [_qb("watson", "Deshaun Watson", "CLE", 1), _qb("sanders", "Shedeur Sanders", "CLE", 3)]

    assert (
        _club_kinds("CLE", browns, "Source: Browns returning to Watson as QB1 despite Sanders' strong fill-in start")
        == []
    )
    # A backup's start while the starter was out, read once the starter is back and fit.
    assert _club_kinds("CLE", browns, "Browns to start Sanders at QB vs. Saints with Watson in protocol") == []


def test_a_club_sticking_with_its_listed_starter_is_no_qb_change() -> None:
    patriots = [_qb("devito", "Tommy DeVito", "NE", 1), _qb("maye", "Drake Maye", "NE", 2, "Out")]

    assert (
        _club_kinds(
            "NE",
            patriots,
            "Vrabel: Patriots sticking with DeVito as QB1, not looking for outside help",
            "The team isn't looking outside the organization for a starting quarterback as it prepares to be "
            "without Drake Maye in the coming weeks due to a fractured right finger.",
        )
        == []
    )


def test_a_backup_named_beside_starting_counts_for_his_own_start() -> None:
    """Three words between 'turn to' and Josh Johnson: still his start."""
    cardinals = [_qb("beck", "Carson Beck", "ARI", 1, "Out"), _qb("johnson", "Josh Johnson", "ARI", 2)]

    assert _club_kinds(
        "ARI", cardinals, "Cardinals rule out rookie Carson Beck, turn to 40-year-old Josh Johnson vs. Chiefs"
    ) == [QB_CHANGE]
