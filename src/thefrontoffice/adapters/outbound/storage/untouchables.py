"""The players the manager marked untouchable, on disk.

One entry per league, beside the to-do decisions, replaced whole on each
change. Kept for a year from the last change: a mark outlasts any season it
was made in only by being renewed.
"""

from datetime import timedelta

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.domain.ports import UntouchableStore

KEEP_FOR = timedelta(days=365)


class DiskUntouchableStore(UntouchableStore):
    def __init__(self, cache: DiskCache) -> None:
        self._cache = cache

    def player_ids(self, scope: str) -> list[str]:
        stored = self._cache.get(scope, KEEP_FOR)
        return [str(pid) for pid in stored] if isinstance(stored, list) else []

    def save(self, scope: str, player_ids: list[str]) -> None:
        self._cache.set(scope, player_ids)
