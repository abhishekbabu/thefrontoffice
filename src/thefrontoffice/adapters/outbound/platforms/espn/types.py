"""What we keep from ESPN's news feeds."""

from dataclasses import dataclass, field
from datetime import datetime

NFL = "football/nfl"
"""ESPN's path for a league: the sport, then the league within it."""


@dataclass(frozen=True)
class NewsArticle:
    """One piece of news, and the players ESPN says it is about."""

    article_id: str
    published: datetime
    """Aware UTC."""

    headline: str
    summary: str = ""
    url: str = ""
    athletes: list[str] = field(default_factory=list)
    """Names as ESPN tags them. An article can name a player in its text
    without tagging him; matching on the text is the caller's decision."""
