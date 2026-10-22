"""The model's latest judgment of each league, kept on disk.

One file per league, replaced on every new judgment: only the latest is
ever read, and the disk cache already writes atomically. Kept for a week,
which is as long as a fantasy week's verdicts can mean anything.
"""

from datetime import timedelta
from pathlib import Path

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.models import Judgment
from thefrontoffice.domain.ports import JudgmentStore

KEEP_FOR = timedelta(days=7)


class DiskJudgmentStore(JudgmentStore):
    def __init__(self, cache: JsonDiskCache | None = None) -> None:
        self._cache = cache or JsonDiskCache(Path(settings.judgment_cache_dir))

    def latest(self, scope: str) -> Judgment | None:
        stored = self._cache.get(f"judgment_{scope}", KEEP_FOR)
        return Judgment.model_validate(stored) if stored is not None else None

    def save(self, scope: str, judgment: Judgment) -> None:
        self._cache.set(f"judgment_{scope}", judgment.model_dump(mode="json"))
