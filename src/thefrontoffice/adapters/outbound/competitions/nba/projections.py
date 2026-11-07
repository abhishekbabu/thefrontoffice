"""Projected nine-category totals for a matchup period.

Sleeper publishes NBA projections one row per player per game. A category
league scores on the totals across the games inside its matchup period, so the
rows for a player are filtered to that window and summed.

The join is by name, because Yahoo and Sleeper share no identifier. That is the
fragile part of this module and it is treated as such: names are normalized, an
ambiguous surname is refused rather than guessed, and a player who cannot be
matched simply carries no projection instead of borrowing someone else's.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.names import NameIndex, normalize_name
from thefrontoffice.adapters.outbound.competitions.nba.rules import BOX_SCORE, Line, line
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectedTotals:
    """A player's projected category totals across a matchup period."""

    games: int
    totals: dict[str, float]
    """Summed Sleeper box-score keys."""

    @property
    def line(self) -> Line:
        """The nine categories as totals over the period, percentages from summed attempts."""
        return line(self.totals)


def aggregate(rows: Iterable[GameProjection]) -> ProjectedTotals:
    """Sum per-game projections into category totals."""
    rows = list(rows)
    totals: dict[str, float] = {}
    for stat in BOX_SCORE:
        value = sum(r.stats.get(stat, 0.0) for r in rows)
        if value:
            totals[stat] = round(value, 2)
    return ProjectedTotals(games=len(rows), totals=totals)


class ProjectionIndex:
    """Projections for a matchup period, looked up by player name."""

    def __init__(self, rows: Iterable[GameProjection], start: date, end: date) -> None:
        grouped: dict[str, list[GameProjection]] = {}
        for row in rows:
            if _within(row.date, start, end):
                grouped.setdefault(normalize_name(row.name), []).append(row)

        self._index: NameIndex[list[GameProjection]] = NameIndex()
        for key, games in grouped.items():
            self._index.add(key, games)

    def __len__(self) -> int:
        return len(self._index)

    @property
    def is_empty(self) -> bool:
        """True out of season, when Sleeper publishes no projections yet."""
        return self._index.is_empty

    def lookup(self, name: str) -> ProjectedTotals | None:
        """Projected totals for `name`, or None if it cannot be matched."""
        rows = self._index.lookup(name)
        return aggregate(rows) if rows else None


def _within(label: str, start: date, end: date) -> bool:
    """Whether a date label falls inside the matchup period."""
    day = parse_day(label)
    return day is not None and start <= day <= end
