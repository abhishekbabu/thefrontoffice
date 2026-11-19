"""The news behind each football player: ESPN's club feeds, joined to Sleeper (`competitions/news.py`).

Sleeper carries ESPN's id for barely a quarter of active players, so the join
is by name within one club, like every competition's; this says which of
Sleeper's players are a club's to read its feed for.
"""

from collections.abc import Mapping
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions import news
from thefrontoffice.adapters.outbound.competitions.news import PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import PlayerInfo
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle


def attach(feeds: dict[str, list[NewsArticle]], players: Mapping[str, PlayerInfo], now: datetime) -> PlayerNews:
    """Each player's articles from the last `news.NEWS_WINDOW`, from his own club's feed."""
    return news.attach(feeds, players_by_club(players), now)
