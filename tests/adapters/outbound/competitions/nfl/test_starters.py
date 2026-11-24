"""Tests for reading a change of starting quarterback off the depth chart: `nfl/starters.py`."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from support.stores import FakeStarterLog

from thefrontoffice.adapters.outbound.competitions.news import NEWS_WINDOW
from thefrontoffice.adapters.outbound.competitions.nfl.news import QB_CHANGE
from thefrontoffice.adapters.outbound.competitions.nfl.starters import changes, starters
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta

NOW = datetime(2026, 11, 24, 18, tzinfo=UTC)
TODAY = NOW.date()

COLTS = {
    "jones": PlayerMeta(player_id="jones", name="Daniel Jones", position="QB", team="FA"),
    "richardson": PlayerMeta(
        player_id="richardson", name="Anthony Richardson Sr.", position="QB", team="IND", depth_chart_order=1
    ),
    "warren": PlayerMeta(player_id="warren", name="Tyler Warren", position="TE", team="IND", depth_chart_order=1),
    "daniels": PlayerMeta(player_id="daniels", name="Jayden Daniels", position="QB", team="WAS", depth_chart_order=1),
}


def _day(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def test_each_clubs_listed_starter_under_espns_spelling() -> None:
    assert starters(COLTS) == {"IND": "richardson", "WSH": "daniels"}


def test_a_starter_changed_since_an_earlier_day_is_a_qb_change_dated_the_first_day_it_read_so() -> None:
    log = FakeStarterLog({_day(5): {"IND": "jones"}, _day(4): {"IND": "jones"}, _day(3): {"IND": "richardson"}})

    found = changes(log, COLTS, NOW)

    [story] = found.values()
    assert list(found) == ["IND"]
    assert story.kind == QB_CHANGE
    assert story.article.published.date() == _day(3)
    # Who starts now and who did, by name; Sleeper has Jones on no club and still names him.
    assert "Anthony Richardson Sr." in story.article.headline and "Daniel Jones" in story.article.headline
    assert log.days[TODAY] == starters(COLTS)


def test_a_change_first_seen_today_is_dated_today() -> None:
    [story] = changes(FakeStarterLog({_day(1): {"IND": "jones"}}), COLTS, NOW).values()

    assert story.article.published.date() == TODAY


def test_an_unchanged_starter_a_day_with_none_listed_and_a_change_past_the_window_are_no_change() -> None:
    log = FakeStarterLog(
        {
            _day(NEWS_WINDOW.days + 1): {"IND": "jones"},
            _day(2): {"IND": "richardson", "WSH": "daniels"},
            _day(1): {},
        }
    )

    assert changes(log, COLTS, NOW) == {}


def test_without_an_earlier_day_kept_nothing_has_changed_yet() -> None:
    assert changes(FakeStarterLog(), COLTS, NOW) == {}


def test_a_club_with_no_listed_starter_today_says_nothing() -> None:
    unlisted = {**COLTS, "richardson": replace(COLTS["richardson"], depth_chart_order=2)}

    assert "IND" not in changes(FakeStarterLog({_day(1): {"IND": "jones"}}), unlisted, NOW)
