"""Tests for keeping each week's pre-game projections on disk: `storage/projections.py`."""

from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.projections import DiskProjectionLog


def test_a_weeks_projections_survive_the_round_trip_and_a_week_not_kept_is_none(tmp_path: Path) -> None:
    DiskProjectionLog(DiskCache(tmp_path)).keep("2026", 12, {"12518": 10.4})

    # A fresh log on the same directory: what a restarted server reads.
    log = DiskProjectionLog(DiskCache(tmp_path))
    assert log.week("2026", 12) == {"12518": 10.4}
    assert log.week("2026", 11) is None
    assert log.week("2025", 12) is None
