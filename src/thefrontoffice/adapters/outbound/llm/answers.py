"""Every kept model answer, on disk.

One file per scope, replaced on each new answer: only the latest is ever
read, and the disk cache already writes atomically. Kept for a week, which is
as long as a fantasy week's answers can mean anything.
"""

from collections.abc import Mapping
from datetime import timedelta

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.storage import scopes
from thefrontoffice.domain.models import Remembered
from thefrontoffice.domain.ports import AnswerStore, TModel

KEEP_FOR = timedelta(days=7)


class DiskAnswerStore(AnswerStore):
    def __init__(self, cache: JsonDiskCache, *, renamed: Mapping[str, str]) -> None:
        """`renamed` maps a competition's registry key to the name its answers were once kept under."""
        self._cache = cache
        self._renamed = renamed

    def latest(self, scope: str, schema: type[TModel]) -> Remembered[TModel] | None:
        stored = scopes.read(self._cache, scope, KEEP_FOR, self._renamed)
        return Remembered[schema].model_validate(stored) if stored is not None else None

    def save(self, scope: str, remembered: Remembered[TModel]) -> None:
        self._cache.set(scope, remembered.model_dump(mode="json"))
