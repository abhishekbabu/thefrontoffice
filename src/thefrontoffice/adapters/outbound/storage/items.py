"""The manager's decisions about to-do items, on disk.

One file per league holding every decision in it, replaced whole on each
change: they are read together on every page load, and there are only ever a
handful. Kept for a season — a decision about week 3 means nothing by week
12, but nor does it cost anything to keep, and expiring it sooner would bring
back a dismissal someone still meant.
"""

from datetime import timedelta
from pathlib import Path

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.models import ItemState
from thefrontoffice.domain.ports import ItemStateStore

KEEP_FOR = timedelta(days=180)


class DiskItemStateStore(ItemStateStore):
    def __init__(self, cache: JsonDiskCache | None = None) -> None:
        self._cache = cache or JsonDiskCache(Path(settings.item_state_dir))

    def states(self, scope: str) -> dict[str, ItemState]:
        stored = self._cache.get(scope, KEEP_FOR) or {}
        return {key: ItemState.model_validate(value) for key, value in stored.items()}

    def save(self, scope: str, states: dict[str, ItemState]) -> None:
        self._cache.set(scope, {key: state.model_dump(mode="json") for key, state in states.items()})
