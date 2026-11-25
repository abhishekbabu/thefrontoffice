"""Tests for reading a club's feed for the stories that change every player's work: `competitions/stories.py`."""

from datetime import UTC, datetime

import pytest

from thefrontoffice.adapters.outbound.competitions.stories import (
    RELEASED,
    RELEASED_BY,
    TRADED,
    TRADED_TO,
    moved,
    near,
    out_long,
    recap,
    roundup,
    sentences,
    talk,
    text_of,
    trade_talk,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

JONES = "daniel jones"


def _story(headline: str, summary: str = "") -> NewsArticle:
    return NewsArticle(article_id="1", published=datetime(2026, 11, 20, tzinfo=UTC), headline=headline, summary=summary)


def _moved(headline: str, verbs: tuple[str, ...], after: tuple[str, ...]) -> bool:
    return moved(text_of(_story(headline)), [JONES], verbs, after, ("", "qb "))


@pytest.mark.parametrize(
    "headline", ["Colts cut QB Daniel Jones", "Colts part ways with Daniel Jones", "Daniel Jones released by Colts"]
)
def test_a_release_moves_the_player_it_takes_as_its_object(headline: str) -> None:
    assert _moved(headline, RELEASED, RELEASED_BY)


@pytest.mark.parametrize(
    "headline", ["Vikings acquire Daniel Jones", "Daniel Jones traded to Vikings", "Deal sends Daniel Jones to Vikings"]
)
def test_a_trade_moves_the_player_it_takes_as_its_object(headline: str) -> None:
    assert _moved(headline, TRADED, TRADED_TO)


def test_a_clause_boundary_keeps_a_verb_from_taking_the_next_clauses_player() -> None:
    """'…in trades, Daniel Jones says' is no trade of Daniel Jones."""
    assert not _moved("Colts add three linebackers in trades, Daniel Jones says", TRADED, TRADED_TO)
    # A generational suffix's full stop is no clause boundary.
    assert "anthony richardson for" in text_of(_story("Colts turn to Anthony Richardson Sr. for next start"))


def test_the_trade_deadline_is_a_date_not_a_trade() -> None:
    assert " trade " not in text_of(_story("Jets keep roster intact at the trade deadline"))


@pytest.mark.parametrize("headline", ["Could the Colts bench Daniel Jones?", "Colts interested in a trade"])
def test_a_question_or_a_rumor_is_talk(headline: str) -> None:
    story = _story(headline)
    assert talk(story, text_of(story))


def test_a_story_of_more_clubs_than_a_trade_names_is_a_roundup() -> None:
    assert not roundup(["IND", "MIN", "IND"])
    assert roundup(["IND", "MIN", "KC"])


@pytest.mark.parametrize(
    ("headline", "long"),
    [
        ("Out for the season", True),
        ("Out indefinitely", True),
        ("Out at least a month", True),
        ("Reevaluated in 8-10 weeks", True),
        ("Sidelined two to four weeks", True),
        ("Out 1-2 weeks", False),
        ("Through 10 weeks, the best offense", False),
        ("Feasting for the past 3 weeks", False),
        ("Played 4 weeks straight", False),
    ],
)
def test_an_absence_is_long_from_the_season_a_month_or_three_weeks_at_the_most(headline: str, long: bool) -> None:
    story = _story(headline)
    assert out_long(story, text_of(story)) is long


def test_a_phrase_is_near_a_player_within_a_few_words_of_one_clause() -> None:
    text = text_of(_story("Cardinals turn to 40-year-old Josh Johnson. Daniel Jones will watch the start"))

    assert near(text, ["josh johnson"], ["turn to"])
    assert not near(text, ["daniel jones"], ["turn to"])
    assert not near(text, ["josh johnson"], ["start"])


@pytest.mark.parametrize(
    ("headline", "is_recap"),
    [
        ("Seahawks beat Raiders 21-13 as Drew Lock throws for 2 TDs", True),
        ("Bulls roll to a 137-107 victory over the Nets", True),
        ("Colts rout Texans 31-3", True),
        ("Anthony Richardson upbeat despite Colts' 3-7 start", False),
        ("Colts beat Texans behind Anthony Richardson", False),
    ],
)
def test_a_recap_has_a_score_and_a_result_in_its_headline(headline: str, is_recap: bool) -> None:
    assert recap(_story(headline)) is is_recap


TURNER = "myles turner"


@pytest.mark.parametrize(
    ("headline", "summary", "talked"),
    [
        ("Bucks' Myles Turner emerging as a trade candidate", "", True),
        ("Shams: Myles Turner has requested a trade from the Bucks", "", True),
        ("Rivals could trade for Myles Turner before the deadline", "", True),
        ("Turner adds 27 as Bucks snap skid", "Myles Turner fouled out with a season-high 27.", False),
        ("Bucks acquire Myles Turner from Pacers", "", False),
        ("Trade candidates to watch", "The Bucks' rebuild goes on. Myles Turner scored 27 on Monday night.", False),
    ],
)
def test_trade_talk_names_the_player_beside_it_and_never_a_trade_made(
    headline: str, summary: str, talked: bool
) -> None:
    assert trade_talk(_story(headline, summary), [TURNER]) is talked


def test_a_storys_text_is_read_a_sentence_at_a_time_with_the_player_named_in_it() -> None:
    """The text talks of trading him in one sentence; in another, a trade talked of is somebody else's."""
    named = NewsArticle(
        article_id="1",
        published=datetime(2026, 11, 20, tzinfo=UTC),
        headline="Bucks notebook",
        body="The Bucks won again. Myles Turner looms as a trade candidate for contenders.",
    )
    apart = NewsArticle(
        article_id="2",
        published=datetime(2026, 11, 20, tzinfo=UTC),
        headline="Bucks notebook",
        body="Myles Turner scored 27. Rivals could trade for Kevin Durant before the deadline.",
    )

    assert trade_talk(named, [TURNER])
    assert not trade_talk(apart, [TURNER])
    assert sentences("One. Two, J.R. Smith said! ") == ["One.", "Two, J.R. Smith said!"]
    assert sentences("") == []
