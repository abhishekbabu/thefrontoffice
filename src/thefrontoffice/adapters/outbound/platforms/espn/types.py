"""What we keep from ESPN: its news feeds, its live scoreboard, its injury report, and who is on each club."""

from dataclasses import dataclass, field
from datetime import date, datetime

NFL = "football/nfl"
"""ESPN's path for a league: the sport, then the league within it."""

NBA = "basketball/nba"


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
    body: str = ""
    """The story's text, tags stripped, where it was read (`ESPNSource.get_stories`); a feed carries none."""
    api_url: str = ""
    """Where ESPN serves the story itself, its text among it; empty for a row without one."""


@dataclass(frozen=True)
class ScoreboardGame:
    """One game as ESPN's scoreboard has it right now: who, the score, which period, and the clock.

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
    home_score: int = 0
    away_score: int = 0
    """Points on the board; nought for each side before kickoff."""
    kickoff: datetime | None = None
    """When it starts, in UTC; None where ESPN gave no time."""


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
    athlete_id: str = ""
    """ESPN's own id for him, read off his player-card link; empty where ESPN gave none."""
    returns: date | None = None
    """ESPN's estimated return: a day, not an instant. None where it gives none."""
    injury: str = ""
    """What and where, in ESPN's words: 'Right elbow, surgery'. Empty where unspecified."""
    comment: str = ""
    """The latest one-line update, as ESPN's report carries it."""
    url: str = ""
    """His news page on ESPN, where the update comes from; empty where ESPN gave none."""


@dataclass(frozen=True)
class Athlete:
    """One player on a club's roster, as ESPN lists him: enough to ask after him by ESPN's own id."""

    athlete_id: str
    name: str
    club: str
    """ESPN's abbreviation."""
