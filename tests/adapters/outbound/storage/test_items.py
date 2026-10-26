"""Tests for keeping item decisions on disk: `storage/items.py`."""

from datetime import UTC, datetime
from pathlib import Path

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore
from thefrontoffice.domain.models import ItemState


def test_decisions_survive_the_round_trip_through_the_file(tmp_path: Path) -> None:
    states = {
        "swap:a:b": ItemState(key="swap:a:b", dismissed_as="abc123"),
        "bye:8:RB": ItemState(key="bye:8:RB", snoozed_until=datetime(2026, 10, 25, 15, tzinfo=UTC)),
    }
    DiskItemStateStore(JsonDiskCache(tmp_path)).save("items:NFL:L1", states)

    # A fresh store on the same directory: what a restarted server reads.
    assert DiskItemStateStore(JsonDiskCache(tmp_path)).states("items:NFL:L1") == states


def test_a_league_with_no_decisions_has_none(tmp_path: Path) -> None:
    assert DiskItemStateStore(JsonDiskCache(tmp_path)).states("items:NFL:L9") == {}
