"""Yahoo Fantasy API type definitions."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


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
class RosteredPlayer:
    name: str
    position: str


@dataclass(frozen=True)
class Matchup:
    """This week's head-to-head, read once for its score, its categories and its dates."""

    start: date
    end: date
    mine: MatchupSide
    opponent: MatchupSide
    opponent_roster: list[RosteredPlayer]
