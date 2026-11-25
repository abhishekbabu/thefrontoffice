"""Tests for a basketball club's stories that reach every one of its players: `nba/news.py`.

How a story is read — its clauses, talk, a move's object — is `competitions/test_stories.py`'s; these
cover which basketball stories count, and how they reach a player's line.
"""

from datetime import UTC, datetime, timedelta

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.news import (
    COACH,
    OUT_LONG,
    TRADE,
    attach,
    block,
    lines_with_team_news,
    talked,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Regular
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

NOW = datetime(2026, 11, 24, 18, tzinfo=UTC)
REGULARS = [
    Regular(player_id="1", name="Luka Doncic", team="LAL"),
    Regular(player_id="2", name="Austin Reaves", team="LAL"),
    Regular(player_id="3", name="Trae Young", team="WAS"),
    Regular(player_id="4", name="Stephen Curry", team="GSW"),
    Regular(player_id="5", name="Jalen Brunson", team="NYK"),
]
REAVES = make_player("Austin Reaves", "SG", team="LAL", key="reaves")
LUKA = make_player("Luka Doncic", "PG", team="LAL", key="luka")


def _article(headline: str, summary: str = "", days_ago: float = 1) -> NewsArticle:
    return NewsArticle(
        article_id=headline, published=NOW - timedelta(days=days_ago), headline=headline, summary=summary
    )


def _kinds(headline: str, summary: str = "", club: str = "LAL") -> list[str]:
    """Austin Reaves' club stories, by kind, from one article in his club's feed."""
    found = attach({club: [_article(headline, summary)]}, [REAVES, LUKA], REGULARS, NOW)
    return [s.kind for s in found.team("reaves")]


@pytest.mark.parametrize(
    "headline",
    ["Lakers acquire Trae Young", "Trae Young traded to Lakers", "Deal sends Trae Young to the Lakers"],
)
def test_a_regular_any_club_trades_is_every_players_trade(headline: str) -> None:
    assert _kinds(headline) == [TRADE]


def test_a_regular_out_for_long_is_every_teammates_story_but_his_own_is_his_news() -> None:
    found = attach(
        {"LAL": [_article("Luka Doncic out at least 4 weeks with hamstring strain")]}, [REAVES, LUKA], REGULARS, NOW
    )

    assert [s.kind for s in found.team("reaves")] == [OUT_LONG]
    assert found.team("luka") == []


@pytest.mark.parametrize(
    "headline",
    [
        "Luka Doncic out for the season",
        "Luka Doncic to be reevaluated in 8-10 weeks",
        "Luka Doncic out at least a month with fractured hand",
        "Luka Doncic sidelined two to four weeks",
    ],
)
def test_each_way_a_story_puts_a_regular_out_for_long(headline: str) -> None:
    assert _kinds(headline) == [OUT_LONG]


@pytest.mark.parametrize(
    "headline",
    [
        "Luka Doncic out 1-2 weeks with ankle sprain",
        "Lakers 10-2 through the first 6 weeks behind Luka Doncic",
        "Luka Doncic has led the Lakers for the past 4 weeks",
        # Another club's regular, out for long, in this club's feed: the opponent's problem.
        "Lakers beat Warriors without Stephen Curry, out for the season",
    ],
)
def test_a_short_absence_the_season_so_far_or_another_clubs_regular_is_no_story(headline: str) -> None:
    assert OUT_LONG not in _kinds(headline)


@pytest.mark.parametrize(
    "headline", ["Lakers fire coach JJ Redick", "Lakers name interim head coach after firing", "Lakers hire head coach"]
)
def test_the_head_coach_changing_hands_is_every_players_story(headline: str) -> None:
    assert _kinds(headline) == [COACH]


@pytest.mark.parametrize(
    "headline",
    [
        "Lakers fire assistant coach",
        "Lakers coach JJ Redick rips team after loss",
        "Could the Lakers fire coach JJ Redick?",
        "Trae Young, Stephen Curry and Jalen Brunson headline trade talk",
    ],
)
def test_an_assistant_a_coachs_words_talk_and_a_roundup_are_no_story(headline: str) -> None:
    assert _kinds(headline) == []


def test_each_line_points_to_its_clubs_stories_stated_once_in_the_block() -> None:
    story = _article("Lakers fire coach JJ Redick")
    found = attach({"LAL": [story]}, [REAVES, LUKA], REGULARS, NOW)

    lines = lines_with_team_news({"Austin Reaves": "- Austin Reaves\n", "Nobody": "- Nobody\n"}, [REAVES], found)
    told = block(found, [REAVES, LUKA])

    assert "LAL" in lines["Austin Reaves"].split("team news", 1)[1]
    assert lines["Nobody"] == "- Nobody\n"
    assert told.count(story.headline) == 1
    assert block(found, [make_player("Free Agent", team="BOS", key="fa")]) == ""


def test_a_player_his_own_news_puts_in_trade_talk_is_named_with_the_story() -> None:
    """Reaves' own story is trade talk; Doncic's recap beside it is not, though both are in the Lakers' feed."""
    feed = [
        _article("Austin Reaves emerges as a trade candidate for the Lakers"),
        _article("Luka Doncic scores 40 as Lakers beat Jazz 120-110", days_ago=2),
    ]
    found = attach({"LAL": feed}, [REAVES, LUKA], REGULARS, NOW)

    told = talked(found, [REAVES, LUKA])

    assert set(told) == {"reaves"}
    assert "trade candidate" in told["reaves"]


def test_his_own_storys_text_may_name_him_by_surname_once_it_names_him_in_full() -> None:
    own = NewsArticle(
        article_id="own",
        published=NOW - timedelta(days=1),
        headline="Lakers mailbag",
        body="Austin Reaves was brilliant on Sunday. League sources say Reaves is a trade candidate.",
    )
    elsewhere = NewsArticle(
        article_id="else",
        published=NOW - timedelta(days=1),
        headline="Lakers mailbag",
        body="Sources say Reaves is a trade candidate.",
    )
    found = attach({}, [REAVES], REGULARS, NOW)

    assert set(talked(found, [REAVES], {"reaves": [own]})) == {"reaves"}
    assert talked(found, [REAVES], {"reaves": [elsewhere]}) == {}
