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


def test_a_club_story_reaches_each_of_its_players_but_one_it_names_stays_his_own_news() -> None:
    from thefrontoffice.adapters.outbound.competitions.news import ClubStory, PlayerNews

    trade, other = _article("Lakers trade for a center"), _article("LeBron James traded", days_ago=2)
    found = PlayerNews(
        by_player={"478.p.3704": [other]},
        by_club={"LAL": [ClubStory(kind="Trade", article=trade), ClubStory(kind="Trade", article=other)]},
        club_of={"478.p.3704": "LAL", "478.p.6014": "LAL"},
    )

    assert [s.article for s in found.team("478.p.6014")] == [trade, other]
    assert [s.article for s in found.team("478.p.3704")] == [trade]
    assert found.team("someone else") == []
    [stat] = [s.stat() for s in found.team("478.p.3704")]
    assert (stat.label, stat.value) == (f"Trade, {dated(trade)}", trade.headline)


def test_a_prompt_points_each_player_at_his_clubs_stories_and_states_them_once() -> None:
    from thefrontoffice.adapters.outbound.competitions.news import ClubStory, PlayerNews, team_block, team_reference

    trade = _article("Lakers trade for a center")
    found = PlayerNews(
        by_club={"LAL": [ClubStory(kind="Trade", article=trade)]},
        club_of={"478.p.3704": "LAL", "478.p.6014": "LAL", "478.p.1": "BOS"},
    )

    assert "LAL" in team_reference(found, "478.p.3704") and "Trade" in team_reference(found, "478.p.3704")
    assert team_reference(found, "478.p.1") == ""
    assert team_block(found, ["478.p.3704", "478.p.6014", "478.p.1"]).count(trade.headline) == 1
    assert team_block(found, ["478.p.1"]) == ""
