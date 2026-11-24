"""Each week's pre-game projections on disk (`nfl/pregame.py`).

Beside the to-do decisions and the depth chart's starters, since like them it is
the app's own record rather than a platform's response. Kept for a season.
"""

from datetime import timedelta

from thefrontoffice.adapters.outbound.cache import DiskCache

KEEP_FOR = timedelta(days=200)
"""A season and its playoffs: a slump reads no week older than the season it is in."""

PREFIX = "nfl-pregame:"


class DiskProjectionLog:
    def __init__(self, cache: DiskCache) -> None:
        self._cache = cache

    def week(self, season: str, week: int) -> dict[str, float] | None:
        stored = self._cache.get(f"{PREFIX}{season}:{week}", KEEP_FOR)
        return {str(pid): float(points) for pid, points in stored.items()} if isinstance(stored, dict) else None

    def keep(self, season: str, week: int, projections: dict[str, float]) -> None:
        self._cache.set(f"{PREFIX}{season}:{week}", projections)
