"""Each player's projection as first read before his game: what a slump measures his game against.

Sleeper serves a past week's projections, but as they stand now: a figure it
revised after the game started — a late scratch, a quarterback ruled out an
hour before kickoff — reads as what the player was expected to do. So each
week it is read, every player's projection is kept the first time it is read
while his club's game has yet to kick off, and never changed after (`record`).
A slump reads that figure where it was kept, and Sleeper's served one for the
weeks before keeping began (`slump.slump`).
"""

from collections.abc import Collection, Iterable, Mapping
from typing import Protocol

from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection


class ProjectionLog(Protocol):
    """Each week's pre-game projections, by player: kept on disk by `storage/projections.py`."""

    def week(self, season: str, week: int) -> dict[str, float] | None:
        """That week's kept projections; None for a week nothing was kept for."""
        ...

    def keep(self, season: str, week: int, projections: dict[str, float]) -> None:
        """Keep these as the week's, replacing what was kept for it."""
        ...


def record(
    log: ProjectionLog, season: str, week: int, projections: Mapping[str, Projection], started: Collection[str]
) -> None:
    """Keep the projection of every player whose club has yet to kick off and who has none kept for the week:
    the first read before his game is the one kept."""
    kept = log.week(season, week) or {}
    fresh = {
        pid: p.points for pid, p in projections.items() if pid not in kept and p.team not in started and p.points > 0
    }
    if fresh:
        log.keep(season, week, kept | fresh)


def kept(log: ProjectionLog, season: str, weeks: Iterable[int]) -> dict[int, dict[str, float]]:
    """The pre-game projections kept for each of these weeks, those with any."""
    return {week: found for week in weeks if (found := log.week(season, week))}
