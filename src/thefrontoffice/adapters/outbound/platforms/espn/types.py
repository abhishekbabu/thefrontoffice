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


@dataclass(frozen=True)
class ScoreboardGame:
    """One game as ESPN's scoreboard has it right now: who, which period, and the clock.

    As ESPN reports it, for any sport it covers: how long a period is, and so
    how much of a game is left, is the sport's question, not the platform's.
    """

    home: str
    away: str
    """ESPN's abbreviations."""
    state: str
    """ESPN's own: `pre`, `in` or `post`."""
    period: int = 0
    clock: float = 0.0
    """Seconds left in the period."""
    label: str = ""
    """How ESPN shows it: 'Q3 13:02', 'Halftime', 'Final'."""


@dataclass(frozen=True)
class InjuryReport:
    """One player on a club's injury report, as ESPN last set it."""

    name: str
    club: str
    """ESPN's abbreviation."""
    status: str
    """ESPN's own: 'Out', 'Doubtful', 'Questionable', 'Injured Reserve', or 'Active' once cleared."""
    updated: datetime
    """Aware UTC."""
