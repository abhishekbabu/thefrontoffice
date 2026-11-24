"""Tests for keeping untouchables on disk: `storage/untouchables.py`."""

from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.untouchables import DiskUntouchableStore


def test_marks_survive_the_round_trip_through_the_file(tmp_path: Path) -> None:
    DiskUntouchableStore(DiskCache(tmp_path)).save("untouchables:nfl-sleeper:L1", ["4881", "9509"])

    # A fresh store on the same directory: what a restarted server reads.
    assert DiskUntouchableStore(DiskCache(tmp_path)).player_ids("untouchables:nfl-sleeper:L1") == ["4881", "9509"]


def test_a_league_with_nobody_marked_has_nobody(tmp_path: Path) -> None:
    assert DiskUntouchableStore(DiskCache(tmp_path)).player_ids("untouchables:nfl-sleeper:L9") == []


def test_every_mark_cleared_is_nobody(tmp_path: Path) -> None:
    store = DiskUntouchableStore(DiskCache(tmp_path))
    store.save("untouchables:nfl-sleeper:L1", ["4881"])
    store.save("untouchables:nfl-sleeper:L1", [])

    assert store.player_ids("untouchables:nfl-sleeper:L1") == []
