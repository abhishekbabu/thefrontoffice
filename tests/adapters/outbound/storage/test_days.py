"""Tests for keeping each basketball day's statuses and minutes on disk: `storage/days.py`."""

from datetime import date
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.days import DiskDayLog


def test_a_days_statuses_and_minutes_survive_the_round_trip_and_a_day_not_kept_is_empty(tmp_path: Path) -> None:
    monday = date(2026, 11, 23)
    DiskDayLog(DiskCache(tmp_path)).keep_statuses(monday, {"466.p.1": "GTD"})
    DiskDayLog(DiskCache(tmp_path)).keep_minutes(monday, {"466.p.1": 0.0, "466.p.2": 31.5})

    # A fresh log on the same directory: what a restarted server reads.
    log = DiskDayLog(DiskCache(tmp_path))
    assert log.statuses(monday) == {"466.p.1": "GTD"}
    assert log.minutes(monday) == {"466.p.1": 0.0, "466.p.2": 31.5}
    assert (log.statuses(date(2026, 11, 24)), log.minutes(date(2026, 11, 24))) == ({}, {})
