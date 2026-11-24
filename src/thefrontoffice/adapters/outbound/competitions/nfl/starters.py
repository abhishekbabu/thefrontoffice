"""Each club's starting quarterback, day by day: a change of starter that no story has reported.

ESPN's feed reports most quarterback changes (`nfl/news.py`), but not all of them,
and a trade or release worded as nothing the rules read goes unnoticed. Sleeper's
depth chart moves either way. So each day the week is read, each club's depth-chart
starter is kept (`StarterLog`), and a club whose starter differs from an earlier
day's within `news.NEWS_WINDOW` has a quarterback change, dated the first day it
read differently, and labelled as the depth chart's.

A club with no listed starter on a day says nothing that day: an empty depth chart
is Sleeper between updates, not a club without a quarterback.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

from thefrontoffice.adapters.outbound.competitions.news import NEWS_WINDOW, ClubStory
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club, on_a_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import PlayerInfo
from thefrontoffice.adapters.outbound.competitions.nfl.news import QB_CHANGE
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

DEPTH_CHART = "Depth chart"
"""Where the headline says the change was read: a `QB_CHANGE` like a story's, from another source."""


class StarterLog(Protocol):
    """Each day's starters, by club: kept on disk by `storage/starters.py`."""

    def day(self, day: date) -> dict[str, str] | None:
        """That day's starters, each club's player id under ESPN's spelling; None for a day not kept."""
        ...

    def keep(self, day: date, starters: dict[str, str]) -> None:
        """Keep today's, replacing anything kept for it earlier the same day."""
        ...


def starters(players: Mapping[str, PlayerInfo]) -> dict[str, str]:
    """Each club's depth-chart starter at quarterback, under ESPN's spelling; no club whose chart lists none."""
    return {
        espn_club(meta.team): pid
        for pid, meta in players.items()
        if on_a_club(meta) and meta.position == "QB" and meta.depth_chart_order == 1
    }


def changes(log: StarterLog, players: Mapping[str, PlayerInfo], now: datetime) -> dict[str, ClubStory]:
    """Each club whose starter changed within the window, as its story; and today's starters kept.

    Days are UTC, like every other label the provider dates a story by.
    """
    today = now.astimezone(UTC).date()
    current = starters(players)
    log.keep(today, current)
    days = [today - timedelta(days=n) for n in range(NEWS_WINDOW.days, 0, -1)]
    kept = [(day, found) for day in days if (found := log.day(day)) is not None]

    found: dict[str, ClubStory] = {}
    for club, now_starts in current.items():
        seen = [(day, starts[club]) for day, starts in kept if starts.get(club)]
        if not seen:
            continue
        # The latest day he was not the starter: the change is the day after it read otherwise.
        before = [(day, pid) for day, pid in seen if pid != now_starts]
        if not before:
            continue
        last_day, was = before[-1]
        since = next((day for day, pid in seen if day > last_day and pid == now_starts), today)
        found[club] = _story(club, since, players.get(now_starts), players.get(was))
    return found


def _story(club: str, since: date, starter: PlayerInfo | None, was: PlayerInfo | None) -> ClubStory:
    """'Depth chart: Anthony Richardson Sr. starts, not Daniel Jones', dated the day it first read so."""
    who = starter.name if starter else "a new starter"
    instead = f", not {was.name}" if was else ""
    article = NewsArticle(
        article_id=f"depth-{club}-{since.isoformat()}",
        published=datetime.combine(since, time(), tzinfo=UTC),
        headline=f"{DEPTH_CHART}: {who} starts{instead}",
    )
    return ClubStory(kind=QB_CHANGE, article=article)
