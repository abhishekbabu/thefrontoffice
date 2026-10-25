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


REGULATION = 4 * 15 * 60
"""Seconds in a regulation game: four fifteen-minute quarters."""


@dataclass(frozen=True)
class ScoreboardGame:
    """One game as ESPN's scoreboard has it right now: who, how far in, and the clock."""

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

    @property
    def left(self) -> float:
        """How much of the game is still to play, from 1 before kickoff to 0 at the end.

        Overtime is read as what is left of its own clock against a whole
        game, which is about right: a few minutes, and it may end at any snap.
        """
        if self.state == "pre":
            return 1.0
        if self.state == "post":
            return 0.0
        if self.period > 4:
            return min(1.0, self.clock / REGULATION)
        played = (max(self.period, 1) - 1) * 15 * 60 + (15 * 60 - self.clock)
        return max(0.0, min(1.0, 1 - played / REGULATION))
