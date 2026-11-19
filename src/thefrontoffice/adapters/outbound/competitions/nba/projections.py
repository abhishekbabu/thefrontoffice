"""Projected nine-category totals for a matchup period.

Sleeper publishes NBA projections one row per player per game. A category
league scores on the totals across the games inside its matchup period, so the
rows for a player are filtered to that window and summed.

The join is by name, because Yahoo and Sleeper share no identifier. That is the
fragile part of this module and it is treated as such: names are normalized, an
ambiguous surname is refused rather than guessed, and a player who cannot be
matched simply carries no projection instead of borrowing someone else's.

Three things keep a borrowed line out:

- Every player Sleeper lists is indexed, including one it projects nothing for
  (ruled out). Indexing only the projected let a name fall through to a surname
  that looked unique: Duncan Robinson, out, read Mitchell Robinson's rebounds.
- A match whose club differs from the league platform's is refused (`lookup`).
- A projection far out of line with his recent run is dropped (`plausible`).
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.names import NameIndex, normalize_name
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.rules import BOX_SCORE, Line, line
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection
from thefrontoffice.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)

IMPLAUSIBLE = 2.5
"""How many times his recent figure a game a projection may be, either way, before it reads as another player's."""

LEEWAY = {"PTS": 6.0, "REB": 4.0, "AST": 3.0, "3PTM": 1.5}
"""The categories `IMPLAUSIBLE` is checked in, and the gap a game under which no ratio counts:
0.3 threes against 0.9 is a cold week, 21 points against 3 is somebody else."""


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
    """Sum per-game projections into category totals; a game projected nothing is no game."""
    rows = [r for r in rows if r.stats]
    totals: dict[str, float] = {}
    for stat in BOX_SCORE:
        value = sum(r.stats.get(stat, 0.0) for r in rows)
        if value:
            totals[stat] = round(value, 2)
    return ProjectedTotals(games=len(rows), totals=totals)


def implausible(projected: ProjectedTotals, recent: Line) -> str | None:
    """The category a projection a game is out of line with `recent` in (`IMPLAUSIBLE`, `LEEWAY`), or None."""
    ahead = line(projected.totals, games=projected.games)
    for label, leeway in LEEWAY.items():
        then, now = recent.get(label, 0.0), ahead.get(label, 0.0)
        high, low = max(then, now), min(then, now)
        if high - low >= leeway and high > IMPLAUSIBLE * low:
            return label
    return None


def plausible(name: str, projected: ProjectedTotals | None, stats: PlayerStats | None) -> ProjectedTotals | None:
    """`projected`, unless it is far out of line with his recent run: then None, and he is read on form alone.

    A projection twenty points a game over what he has been scoring is not a
    forecast of a breakout but, far likelier, a line matched to the wrong man.
    Without a recent run to hold it against, it stands.
    """
    run = stats.get("recent") if stats else None
    if projected is None or not projected.games or run is None:
        return projected
    if (label := implausible(projected, run.line)) is None:
        return projected
    ahead = line(projected.totals, games=projected.games).get(label, 0.0)
    logger.warning(
        f"Dropping {name}'s projection: {ahead:.1f} {label} a game against {run.line.get(label, 0.0):.1f} "
        f"over his last {run.games}"
    )
    return None


class ProjectionIndex:
    """Projections for a matchup period, looked up by player name."""

    def __init__(self, rows: Iterable[GameProjection], start: date, end: date) -> None:
        self._games: dict[str, list[GameProjection]] = {}
        self._clubs: dict[str, str] = {}
        named: dict[str, set[str]] = {}
        for row in rows:
            if _within(row.date, start, end):
                self._games.setdefault(row.player_id, []).append(row)
                self._clubs[row.player_id] = row.team.upper()
                named.setdefault(normalize_name(row.name), set()).add(row.player_id)

        # Two players under one name are neither of them: the name cannot say which.
        self._index: NameIndex[str] = NameIndex()
        for name, ids in named.items():
            if len(ids) == 1:
                self._index.add(name, next(iter(ids)))
        self._projected = sum(1 for games in self._games.values() if any(g.stats for g in games))

    def __len__(self) -> int:
        """Players projected something in the period."""
        return self._projected

    @property
    def is_empty(self) -> bool:
        """True out of season, when Sleeper publishes no projections yet."""
        return not self._projected

    def lookup(self, name: str, club: str = "") -> ProjectedTotals | None:
        """Projected totals for `name`, or None if he cannot be matched or is projected nothing.

        With `club`, a match on another club is refused: a surname that only
        looked unique, or a player Sleeper still lists where he used to play.
        """
        player_id = self._index.lookup(name)
        if player_id is None:
            return None
        if club and (theirs := self._clubs[player_id]) and theirs != club.upper():
            logger.warning(f"Not projecting {name} ({club.upper()}): Sleeper's match plays for {theirs}")
            return None
        totals = aggregate(self._games[player_id])
        return totals if totals.games else None

    def find(self, name: str, club: str, stats: PlayerStats | None) -> ProjectedTotals | None:
        """His projection, matched on his club (`lookup`) and held against his recent run (`plausible`)."""
        return plausible(name, self.lookup(name, club), stats)


def _within(label: str, start: date, end: date) -> bool:
    """Whether a date label falls inside the matchup period."""
    day = parse_day(label)
    return day is not None and start <= day <= end


def index_for(sleeper: SleeperProjectionSource, start: date | None, end: date | None) -> ProjectionIndex | None:
    """Projected category totals for a matchup period, or None.

    Returns None rather than raising when projections are unavailable —
    Sleeper publishes none before opening night, and a scout report built
    from recent form alone is the behavior this had all along.
    """
    if start is None or end is None:
        return None
    try:
        state = sleeper.get_nba_state()
        rows = sleeper.get_nba_projections(state.season, state.week)
        if not rows and state.week:
            # A matchup can straddle two Sleeper weeks near a boundary.
            rows = sleeper.get_nba_projections(state.season, state.week + 1)
        index = ProjectionIndex(rows, start, end)
    except FrontOfficeError as e:
        logger.warning(f"No NBA projections available, using recent form only: {e}")
        return None

    if index.is_empty:
        logger.info("Sleeper has no NBA projections for this period (out of season?)")
        return None
    logger.debug(f"Matched projections for {len(index)} players")
    return index
