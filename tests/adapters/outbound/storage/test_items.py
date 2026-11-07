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
    DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).save("items:NFL:L1", states)

    # A fresh store on the same directory: what a restarted server reads.
    assert DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).states("items:NFL:L1") == states


def test_a_league_with_no_decisions_has_none(tmp_path: Path) -> None:
    assert DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).states("items:NFL:L9") == {}


# ── decisions kept under a competition's former name ────────────────────

RENAMED = {"nfl-sleeper": "NFL (Sleeper)"}
DISMISSED = {"swap:a:b": ItemState(key="swap:a:b", dismissed_as="abc123")}


def test_a_decision_kept_under_the_label_is_found_under_the_key(tmp_path: Path) -> None:
    """Decisions were once filed under the competition's label; none is lost to keying them by entry."""
    DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).save("items:NFL (Sleeper):L1", DISMISSED)

    assert DiskItemStateStore(JsonDiskCache(tmp_path), renamed=RENAMED).states("items:nfl-sleeper:L1") == DISMISSED


def test_a_decision_found_under_the_label_is_refiled_under_the_key(tmp_path: Path) -> None:
    DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).save("items:NFL (Sleeper):L1", DISMISSED)
    DiskItemStateStore(JsonDiskCache(tmp_path), renamed=RENAMED).states("items:nfl-sleeper:L1")

    assert DiskItemStateStore(JsonDiskCache(tmp_path), renamed={}).states("items:nfl-sleeper:L1") == DISMISSED


def test_every_decision_restored_under_the_key_does_not_bring_the_old_ones_back(tmp_path: Path) -> None:
    store = DiskItemStateStore(JsonDiskCache(tmp_path), renamed=RENAMED)
    store.save("items:NFL (Sleeper):L1", DISMISSED)
    store.save("items:nfl-sleeper:L1", {})

    assert store.states("items:nfl-sleeper:L1") == {}
