"""Each club's depth-chart starters, one entry a day, on disk (`nfl/starters.py`).

Beside the to-do decisions, since like them it is the app's own record rather
than a platform's response. Read back no further than `KEEP_FOR`.
"""

from datetime import date, timedelta

from thefrontoffice.adapters.outbound.cache import DiskCache

KEEP_FOR = timedelta(days=30)
"""Longer than any window a change is reported within."""

PREFIX = "nfl-starters:"


class DiskStarterLog:
    def __init__(self, cache: DiskCache) -> None:
        self._cache = cache

    def day(self, day: date) -> dict[str, str] | None:
        stored = self._cache.get(f"{PREFIX}{day.isoformat()}", KEEP_FOR)
        return {str(club): str(pid) for club, pid in stored.items()} if isinstance(stored, dict) else None

    def keep(self, day: date, starters: dict[str, str]) -> None:
        self._cache.set(f"{PREFIX}{day.isoformat()}", starters)
