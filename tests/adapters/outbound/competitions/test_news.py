"""Tests for joining ESPN's club news to any league platform's players: `competitions/news.py`."""

from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.injuries import by_club
from thefrontoffice.adapters.outbound.competitions.news import NEWS_WINDOW, attach, dated
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
CLUBS = by_club([("LAL", "LeBron James", "478.p.3704"), ("LAL", "Luka Doncic", "478.p.6014")])


def _article(headline: str, days_ago: float = 1, athletes: tuple[str, ...] = ()) -> NewsArticle:
    return NewsArticle(
        article_id=headline, published=NOW - timedelta(days=days_ago), headline=headline, athletes=list(athletes)
    )


def test_a_player_is_matched_by_tag_or_full_name_newest_first_keyed_as_the_platform_keys_him() -> None:
    news = {"LAL": [_article("Luka Doncic scores 40", days_ago=2), _article("Return set", athletes=("Luka Doncic",))]}

    found = attach(news, CLUBS, NOW)

    assert [a.headline for a in found.latest("478.p.6014", limit=5)] == ["Return set", "Luka Doncic scores 40"]
    assert found.latest("478.p.3704") == []


def test_news_older_than_the_window_is_left_out() -> None:
    stale = _article("LeBron James rests", days_ago=NEWS_WINDOW.days + 1)

    assert attach({"LAL": [stale]}, CLUBS, NOW).by_player == {}


def test_each_headline_reads_as_its_day_linked_to_its_article() -> None:
    article = _article("LeBron James questionable", days_ago=0)

    [stat] = attach({"LAL": [article]}, CLUBS, NOW).stats("478.p.3704")

    assert (stat.label, stat.value) == (dated(article), "LeBron James questionable")
