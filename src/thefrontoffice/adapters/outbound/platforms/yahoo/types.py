"""Yahoo Fantasy API type definitions.

What the client reads out of Yahoo's responses, once, so nothing beyond this
package touches the SDK's objects — which get their attributes by `setattr` at
runtime and promise none of them.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from thefrontoffice.domain.models import record


class PlayerStatus(StrEnum):
    """Yahoo API player status filter values."""

    ALL_AVAILABLE = "A"
    FREE_AGENT = "FA"
    WAIVERS = "W"
    TAKEN = "T"
    KEEPERS = "K"


class PlayerStat(StrEnum):
    """Yahoo API sort fields that are not a stat.

    A sport's own stat ids sort too, and belong to that sport's rules.
    """

    OVERALL_RANK = "OR"
    ACTUAL_RANK = "AR"
    FANTASY_POINTS = "PTS"
    NAME = "NAME"


class Timeframe(StrEnum):
    """Yahoo API time window values for sorting."""

    SEASON = "season"
    DATE = "date"
    LAST_WEEK = "lastweek"
    LAST_MONTH = "lastmonth"


@dataclass(frozen=True)
class MatchupSide:
    """One team's side of a head-to-head week."""

    team_key: str
    name: str
    points: str
    """Yahoo's score for the side, as it prints it: categories won, in a category league."""

    stats: dict[str, str]
    """Yahoo stat id -> the side's value, as Yahoo prints it."""


@dataclass(frozen=True)
class YahooLeague:
    """One league the login plays in."""

    league_key: str
    """'466.l.123': the game, then the league. Every request about the league names it."""

    name: str
    league_type: str = ""
    current_week: int | None = None
    """None between seasons, when there is no week to read."""


@dataclass(frozen=True)
class YahooPlayer:
    player_key: str
    name: str
    position: str
    """Every position the player is eligible at, as Yahoo prints it: 'PF,C'."""

    team: str
    """The NBA team's abbreviation."""

    status: str = ""
    """'O', 'GTD', 'INJ'; empty for a player with nothing reported."""

    injury_note: str = ""
    slot: str = ""
    """Where their manager has them this week: 'PG', 'BN', 'IL'. Empty off a roster."""


@dataclass(frozen=True)
class TeamStanding:
    rank: int
    wins: int
    losses: int
    ties: int
    points_for: str
    """As Yahoo prints it; empty where it gives none."""

    @property
    def record(self) -> str:
        return record(self.wins, self.losses, self.ties)


@dataclass(frozen=True)
class YahooTeam:
    team_key: str
    """'nba.l.123.t.4': the league, then the team."""

    name: str
    is_mine: bool = False
    """Owned by the login reading it."""

    adds_used: int = 0
    """Adds made this week, against the league's weekly limit."""

    standing: TeamStanding | None = None
    """None where Yahoo sent no standings with the team."""


@dataclass(frozen=True)
class Matchup:
    """This week's head-to-head, read once for its score, its categories and its dates."""

    start: date
    end: date
    mine: MatchupSide
    opponent: MatchupSide
    opponent_roster: list[YahooPlayer]
