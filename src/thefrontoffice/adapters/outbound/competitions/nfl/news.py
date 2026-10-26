"""The news behind each football player: ESPN's club feeds, joined to Sleeper.

Sleeper says *that* a player is questionable; the news says why, and what it
means for who gets the work. The two platforms share no player identifier —
Sleeper carries ESPN's for barely a quarter of active players — so the join
is by name, within one club, and refuses to guess:

- an article is read only for the players of the club whose feed it is in,
  which is what keeps the Bills' Josh Allen from inheriting news about
  anybody else of that name;
- a player matches on ESPN's own tag, or on his full name in the headline or
  summary — never a surname alone;
- two players on one club with the same name match nothing, rather than both
  inheriting each other's news.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle
from thefrontoffice.adapters.outbound.platforms.sleeper.types import FANTASY_POSITIONS, PlayerMeta
from thefrontoffice.domain.models import Stat

logger = logging.getLogger(__name__)

NEWS_WINDOW = timedelta(days=10)
"""Long enough to span a bye week, short enough that it is still this role."""

# A team defense is filed under the club's own name, and every article about
# the club would read as news about it.
NOT_PLAYERS = frozenset({"DEF"})


@dataclass(frozen=True)
class PlayerNews:
    """Recent articles about each player, newest first, keyed by Sleeper's id."""

    by_player: dict[str, list[NewsArticle]] = field(default_factory=dict)

    def latest(self, player_id: str, limit: int = 1) -> list[NewsArticle]:
        return self.by_player.get(player_id, [])[:limit]

    def stats(self, player_id: str, limit: int = 3) -> list[Stat]:
        """The newest few, each labelled with the day it was published."""
        return [Stat(label=dated(a), value=a.headline) for a in self.latest(player_id, limit)]


def dated(article: NewsArticle) -> str:
    """'Thu 22 Oct'. UTC, like every other timestamp label the provider shows."""
    return weekday_day_month(article.published.date())


def attach(news: dict[str, list[NewsArticle]], players: dict[str, PlayerMeta], now: datetime) -> PlayerNews:
    """Each player's articles from the last `NEWS_WINDOW`, from his own club's feed."""
    clubs: dict[str, dict[str, str | None]] = defaultdict(dict)
    for player_id, meta in players.items():
        team, position, name = str(meta.get("team") or ""), str(meta.get("position") or ""), meta.get("name")
        if not team or team == "FA" or position not in FANTASY_POSITIONS or position in NOT_PLAYERS or not name:
            continue
        key = normalize_name(str(name))
        if not key:
            continue
        roster = clubs[espn_club(team)]
        # A name already taken on this club is nobody's: None marks it so a
        # third player of the name cannot claim it either.
        roster[key] = None if key in roster else player_id

    by_player: dict[str, list[NewsArticle]] = defaultdict(list)
    for club, names in clubs.items():
        for article in news.get(club, []):
            if now - article.published > NEWS_WINDOW:
                continue
            tagged = {normalize_name(name) for name in article.athletes}
            text = f" {normalize_name(f'{article.headline} {article.summary}')} "
            for key, player_id in names.items():
                if player_id and (key in tagged or f" {key} " in text):
                    by_player[player_id].append(article)

    for articles in by_player.values():
        articles.sort(key=lambda a: a.published, reverse=True)
    return PlayerNews(by_player=dict(by_player))
