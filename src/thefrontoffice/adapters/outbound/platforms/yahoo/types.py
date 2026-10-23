"""
Yahoo Fantasy API type definitions.
"""

from dataclasses import dataclass
from enum import StrEnum


class PlayerStatus(StrEnum):
    """Yahoo API player status filter values."""

    ALL_AVAILABLE = "A"
    FREE_AGENT = "FA"
    WAIVERS = "W"
    TAKEN = "T"
    KEEPERS = "K"


class PlayerStat(StrEnum):
    """Yahoo API player stat / sort field values."""

    OVERALL_RANK = "OR"
    ACTUAL_RANK = "AR"
    FANTASY_POINTS = "PTS"
    NAME = "NAME"
    # Stat category IDs (sort by individual stat)
    FG_PCT = "5"
    FT_PCT = "8"
    THREE_PTM = "10"
    POINTS = "12"
    REBOUNDS = "15"
    ASSISTS = "16"
    STEALS = "17"
    BLOCKS = "18"
    TURNOVERS = "19"


class Timeframe(StrEnum):
    """Yahoo API time window values for sorting."""

    SEASON = "season"
    DATE = "date"
    LAST_WEEK = "lastweek"
    LAST_MONTH = "lastmonth"


@dataclass
class MatchupInfo:
    """The current matchup, fetched once and used for both context and dates."""

    context: str = ""
    week_start: str = ""
    week_end: str = ""

    @property
    def has_dates(self) -> bool:
        return bool(self.week_start and self.week_end)
