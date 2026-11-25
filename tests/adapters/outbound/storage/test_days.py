"""Tests for keeping each basketball day's statuses and minutes on disk: `storage/days.py`."""

from datetime import date
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.competitions.nba.day import Hurt
from thefrontoffice.adapters.outbound.storage.days import DiskDayLog


def test_a_days_statuses_and_minutes_survive_the_round_trip_and_a_day_not_kept_is_empty(tmp_path: Path) -> None:
    monday = date(2026, 11, 23)
    DiskDayLog(DiskCache(tmp_path)).keep_statuses(monday, {"466.p.1": "GTD"})
    DiskDayLog(DiskCache(tmp_path)).keep_minutes(monday, {"466.p.1": 0.0, "466.p.2": 31.5})
    DiskDayLog(DiskCache(tmp_path)).keep_pregame(monday, {"466.p.1": "Q"})

    # A fresh log on the same directory: what a restarted server reads.
    log = DiskDayLog(DiskCache(tmp_path))
    assert log.statuses(monday) == {"466.p.1": "GTD"}
    assert log.minutes(monday) == {"466.p.1": 0.0, "466.p.2": 31.5}
    assert log.pregame(monday) == {"466.p.1": "Q"}
    other = date(2026, 11, 24)
    assert (log.statuses(other), log.minutes(other), log.pregame(other)) == ({}, {}, {})


def test_the_seasons_injuries_survive_the_round_trip(tmp_path: Path) -> None:
    kept = {
        "466.p.1": [
            Hurt("Left hip, soreness", date(2026, 11, 18), date(2026, 11, 23)),
            Hurt("Rest", date(2026, 11, 24), date(2026, 11, 24), rest=True),
        ]
    }
    DiskDayLog(DiskCache(tmp_path)).keep_injuries(kept)

    assert DiskDayLog(DiskCache(tmp_path)).injuries() == kept
    assert DiskDayLog(DiskCache(tmp_path / "empty")).injuries() == {}
