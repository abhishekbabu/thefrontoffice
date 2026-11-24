"""Tests for keeping each day's depth-chart starters on disk: `storage/starters.py`."""

from datetime import date
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.starters import DiskStarterLog

DAY = date(2026, 11, 20)


def test_a_days_starters_survive_the_round_trip_and_a_day_not_kept_is_none(tmp_path: Path) -> None:
    DiskStarterLog(DiskCache(tmp_path)).keep(DAY, {"IND": "9229"})

    # A fresh log on the same directory: what a restarted server reads.
    log = DiskStarterLog(DiskCache(tmp_path))
    assert log.day(DAY) == {"IND": "9229"}
    assert log.day(date(2026, 11, 21)) is None


def test_a_later_read_the_same_day_replaces_the_earlier(tmp_path: Path) -> None:
    log = DiskStarterLog(DiskCache(tmp_path))
    log.keep(DAY, {"IND": "5870"})
    log.keep(DAY, {"IND": "9229"})

    assert log.day(DAY) == {"IND": "9229"}
