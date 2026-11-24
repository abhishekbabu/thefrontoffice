"""The news behind each player: ESPN's club feeds, joined to a league platform's players by name.

A status says *that* a player is questionable; the news says why, and what it
means for who gets the work. ESPN shares no player identifier with the league
platforms, so the join is by name, within one club, and refuses to guess:

- an article is read only for the players of the club whose feed it is in,
  which is what keeps the Bills' Josh Allen from inheriting news about
  anybody else of that name;
- a player matches on ESPN's own tag, or on his full name in the headline or
  summary — never a surname alone;
- two players on one club with the same name match nothing, rather than both
  inheriting each other's news (`injuries.by_club`).

A club's story that names none of its players can still change every one of
their weeks — a new quarterback, a trade, a new play caller. Which of a feed's
articles those are is each competition's to say; they reach each player on the
club as his team news (`ClubStory`), apart from his own.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.injuries import Clubs
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle
from thefrontoffice.domain.models import Stat

NEWS_WINDOW = timedelta(days=10)
"""Long enough to span a bye week, short enough that it is still this role."""


@dataclass(frozen=True)
class ClubStory:
    """An article about a club that changes its players' work without naming them all."""

    kind: str
    """What changed, as a label: 'QB change', 'Trade'."""
    article: NewsArticle

    def stat(self) -> Stat:
        """'QB change, Sun 23 Nov', linked to the article."""
        return Stat(label=f"{self.kind}, {dated(self.article)}", value=self.article.headline, url=self.article.url)


@dataclass(frozen=True)
class PlayerNews:
    """Recent articles about each player, newest first, keyed by the league platform's id."""

    by_player: dict[str, list[NewsArticle]] = field(default_factory=dict)
    by_club: dict[str, list[ClubStory]] = field(default_factory=dict)
    """Each club's stories, newest first, under the feed's spelling of the club."""
    club_of: dict[str, str] = field(default_factory=dict)
    """Each player's club, under the same spelling: whose stories are his."""

    def latest(self, player_id: str, limit: int = 1) -> list[NewsArticle]:
        return self.by_player.get(player_id, [])[:limit]

    def stats(self, player_id: str, limit: int = 3) -> list[Stat]:
        """The newest few, each labelled with the day it was published and linked to the article."""
        return [Stat(label=dated(a), value=a.headline, url=a.url) for a in self.latest(player_id, limit)]

    def team(self, player_id: str, limit: int = 3) -> list[ClubStory]:
        """His club's newest stories, leaving out any that names him: that one is already his own news."""
        own = {a.article_id for a in self.by_player.get(player_id, [])}
        stories = self.by_club.get(self.club_of.get(player_id, ""), [])
        return [s for s in stories if s.article.article_id not in own][:limit]


def dated(article: NewsArticle) -> str:
    """'Thu 22 Oct'. UTC, like every other timestamp label the provider shows."""
    return weekday_day_month(article.published.date())


def recent(article: NewsArticle, now: datetime) -> bool:
    """Whether it was published within `NEWS_WINDOW`."""
    return now - article.published <= NEWS_WINDOW


def mentioned(article: NewsArticle, keys: Iterable[str]) -> set[str]:
    """Which of these normalized names the article is about: ESPN's own tag, or the full name in its text."""
    tagged = {normalize_name(name) for name in article.athletes}
    text = f" {normalize_name(f'{article.headline} {article.summary}')} "
    return {key for key in keys if key and (key in tagged or f" {key} " in text)}


def attach(news: dict[str, list[NewsArticle]], clubs: Clubs, now: datetime) -> PlayerNews:
    """Each player's articles from the last `NEWS_WINDOW`, from his own club's feed.

    `news` is each club's feed and `clubs` each club's players by normalized
    name, both under ESPN's spelling of the club.
    """
    by_player: dict[str, list[NewsArticle]] = defaultdict(list)
    for club, names in clubs.items():
        for article in news.get(club, []):
            if not recent(article, now):
                continue
            for key in mentioned(article, names):
                if player_id := names[key]:
                    by_player[player_id].append(article)

    for articles in by_player.values():
        articles.sort(key=lambda a: a.published, reverse=True)
    return PlayerNews(by_player=dict(by_player))
