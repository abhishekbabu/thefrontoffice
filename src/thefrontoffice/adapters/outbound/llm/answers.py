"""Every kept model answer, on disk.

One file per scope, replaced on each new answer: only the latest is ever
read, and the disk cache already writes atomically. Kept for a week, which is
as long as a fantasy week's answers can mean anything.
"""

from datetime import timedelta
from pathlib import Path

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.models import Remembered
from thefrontoffice.domain.ports import AnswerStore, TModel

KEEP_FOR = timedelta(days=7)


class DiskAnswerStore(AnswerStore):
    def __init__(self, cache: JsonDiskCache | None = None) -> None:
        self._cache = cache or JsonDiskCache(Path(settings.answer_cache_dir))

    def latest(self, scope: str, schema: type[TModel]) -> Remembered[TModel] | None:
        stored = self._cache.get(scope, KEEP_FOR)
        return Remembered[schema].model_validate(stored) if stored is not None else None

    def save(self, scope: str, remembered: Remembered[TModel]) -> None:
        self._cache.set(scope, remembered.model_dump(mode="json"))
