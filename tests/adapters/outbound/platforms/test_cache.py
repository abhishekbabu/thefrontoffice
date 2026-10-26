"""Tests for the shared JSON disk cache.

The store every platform reads through, so three things matter: what it keeps,
the freshness rules that decide when what it kept stopped being true, and the
one-file-per-key layout that keeps a write proportional to the entry rather
than to everything else already stored.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache, within

HOUR = timedelta(hours=1)
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _entry_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def _write_entry(directory: Path, key: str, entry: object) -> Path:
    """Store `entry` where the cache will look for `key`."""
    from thefrontoffice.adapters.outbound.platforms.cache import _filename

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _filename(key)
    path.write_text(json.dumps(entry), encoding="utf-8")
    return path


def test_value_round_trips(tmp_path: Path) -> None:
    c = JsonDiskCache(tmp_path / "cache")
    c.set("k", {"a": 1}, now=T0)
    assert c.get("k", HOUR, now=T0) == {"a": 1}


def test_value_persists_across_instances(tmp_path: Path) -> None:
    JsonDiskCache(tmp_path / "cache").set("k", [1, 2], now=T0)
    assert JsonDiskCache(tmp_path / "cache").get("k", HOUR, now=T0) == [1, 2]


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    """A first run reads before anything has ever been written."""
    assert JsonDiskCache(tmp_path / "never-created").get("k", HOUR) is None


def test_expired_value_is_none(tmp_path: Path) -> None:
    c = JsonDiskCache(tmp_path / "cache")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0 + timedelta(minutes=59)) == "v"
    assert c.get("k", HOUR, now=T0 + timedelta(hours=1, seconds=1)) is None


def test_each_key_has_its_own_ttl(tmp_path: Path) -> None:
    """Projections and live matchup scores go stale at very different rates."""
    c = JsonDiskCache(tmp_path / "cache")
    c.set("slow", "v", now=T0)
    c.set("fast", "v", now=T0)
    later = T0 + timedelta(minutes=30)
    assert c.get("slow", timedelta(hours=6), now=later) == "v"
    assert c.get("fast", timedelta(minutes=2), now=later) is None


# ── one file per key ────────────────────────────────────────────────────


def test_each_key_gets_its_own_file(tmp_path: Path) -> None:
    """The point of the layout: storing one entry does not rewrite the others."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("players_nfl", {"big": "catalog"}, now=T0)
    c.set("state_nfl", {"week": 3}, now=T0)

    assert len(_entry_files(directory)) == 2


def test_a_write_leaves_other_entries_untouched(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("first", "v", now=T0)
    (written,) = _entry_files(directory)
    before = written.read_bytes()

    c.set("second", "v", now=T0)

    assert written.read_bytes() == before


def test_keys_that_no_filesystem_would_accept_still_round_trip(tmp_path: Path) -> None:
    """A Yahoo player search puts arbitrary user text straight into the key."""
    c = JsonDiskCache(tmp_path / "cache")
    key = "player_search_nba.l.12345_de'aaron fox/jr. ünïcode"
    c.set(key, "found", now=T0)

    assert JsonDiskCache(tmp_path / "cache").get(key, HOUR, now=T0) == "found"


def test_keys_differing_only_in_case_do_not_collide(tmp_path: Path) -> None:
    """macOS and Windows fold case, so the digest has to carry the difference."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("Team", "upper", now=T0)
    c.set("team", "lower", now=T0)

    assert len(_entry_files(directory)) == 2
    fresh = JsonDiskCache(directory)
    assert fresh.get("Team", HOUR, now=T0) == "upper"
    assert fresh.get("team", HOUR, now=T0) == "lower"


def test_a_very_long_key_stays_a_usable_filename(tmp_path: Path) -> None:
    """Windows still enforces a path limit once a deep repo path is prefixed."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("x" * 500, "v", now=T0)

    (written,) = _entry_files(directory)
    assert len(written.name) < 120
    assert JsonDiskCache(directory).get("x" * 500, HOUR, now=T0) == "v"


def test_the_filename_is_recognisable(tmp_path: Path) -> None:
    """The slug is there so a human can read the directory."""
    directory = tmp_path / "cache"
    JsonDiskCache(directory).set("players_nfl", "v", now=T0)

    (written,) = _entry_files(directory)
    assert written.name.startswith("players_nfl-")


# ── durability ──────────────────────────────────────────────────────────


def test_a_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    JsonDiskCache(directory).set("k", "v", now=T0)

    assert list(directory.iterdir()) == _entry_files(directory)


def test_an_unserialisable_value_raises_and_leaves_nothing_behind(tmp_path: Path) -> None:
    """A bug worth surfacing, but not worth littering the directory over."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)

    with pytest.raises(TypeError):
        c.set("k", {1, 2, 3}, now=T0)

    assert list(directory.iterdir()) == []


def test_a_corrupt_entry_is_discarded_not_fatal(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    directory.mkdir()
    _write_entry(directory, "k", {"stored_at": T0.isoformat(), "value": "v"})
    (path,) = _entry_files(directory)
    path.write_text("{not json", encoding="utf-8")

    c = JsonDiskCache(directory)
    assert c.get("k", HOUR, now=T0) is None
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"


def test_one_corrupt_entry_does_not_lose_the_others(tmp_path: Path) -> None:
    """One unreadable file costs its own key and nothing else."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("good", "kept", now=T0)
    _write_entry(directory, "bad", "not an envelope").write_text("{not json", encoding="utf-8")

    fresh = JsonDiskCache(directory)
    assert fresh.get("bad", HOUR, now=T0) is None
    assert fresh.get("good", HOUR, now=T0) == "kept"


def test_an_entry_that_is_not_an_envelope_is_discarded(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _write_entry(directory, "k", [1, 2, 3])
    assert JsonDiskCache(directory).get("k", HOUR) is None


def test_an_envelope_without_a_timestamp_is_discarded(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _write_entry(directory, "k", {"value": "v"})
    assert JsonDiskCache(directory).get("k", HOUR, now=T0) is None


def test_naive_timestamp_is_treated_as_unusable(tmp_path: Path) -> None:
    """Without a zone the entry cannot be placed on a timeline."""
    directory = tmp_path / "cache"
    _write_entry(directory, "k", {"stored_at": "2026-09-01T12:00:00", "value": "v"})
    assert JsonDiskCache(directory).get("k", HOUR, now=T0) is None


def test_unparseable_timestamp_is_treated_as_unusable(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _write_entry(directory, "k", {"stored_at": "whenever", "value": "v"})
    assert JsonDiskCache(directory).get("k", HOUR, now=T0) is None


def test_non_string_timestamp_is_treated_as_unusable(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _write_entry(directory, "k", {"stored_at": 1234, "value": "v"})
    assert JsonDiskCache(directory).get("k", HOUR, now=T0) is None


def test_unwritable_path_does_not_raise(tmp_path: Path) -> None:
    """A cache we cannot persist still has to work for this run."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    c = JsonDiskCache(blocker / "sub")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"


def test_clear_empties_the_cache(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("k", "v", now=T0)
    c.clear()
    assert c.get("k", HOUR, now=T0) is None
    assert _entry_files(directory) == []


def test_clear_leaves_the_directory_and_anything_else_in_it(tmp_path: Path) -> None:
    """A misconfigured path should cost nothing it did not put there."""
    directory = tmp_path / "cache"
    c = JsonDiskCache(directory)
    c.set("k", "v", now=T0)
    stranger = directory / "not-ours.txt"
    stranger.write_text("keep me", encoding="utf-8")

    c.clear()

    assert directory.exists()
    assert stranger.read_text(encoding="utf-8") == "keep me"


def test_clear_on_a_cache_never_written_is_harmless(tmp_path: Path) -> None:
    JsonDiskCache(tmp_path / "never-created").clear()


# ── freshness rules ─────────────────────────────────────────────────────


def test_a_rule_a_duration_cannot_express(tmp_path: Path) -> None:
    """The reason freshness is a predicate: basketball's gamelog is good until
    the next boundary passes, which is a moment rather than an interval."""
    cache = JsonDiskCache(tmp_path / "cache")
    stored = datetime(2026, 2, 9, 12, tzinfo=UTC)
    cache.set("k", "v", now=stored)

    # Good only while stored and now fall on the same calendar day.
    def same_day(at: datetime, now: datetime) -> bool:
        return at.date() == now.date()

    assert cache.get("k", same_day, now=stored + timedelta(hours=6)) == "v"
    assert cache.get("k", same_day, now=stored + timedelta(hours=13)) is None


def test_within_is_a_ttl_as_a_rule(tmp_path: Path) -> None:
    """So a caller can hold one and a caller can hold the other."""
    cache = JsonDiskCache(tmp_path / "cache")
    stored = datetime(2026, 2, 9, 12, tzinfo=UTC)
    cache.set("k", "v", now=stored)

    rule = within(timedelta(minutes=30))
    assert cache.get("k", rule, now=stored + timedelta(minutes=10)) == "v"
    assert cache.get("k", rule, now=stored + timedelta(minutes=40)) is None


# ── read-through ────────────────────────────────────────────────────────


def test_a_hit_never_calls_the_fetch(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    cache.set("k", "stored")
    calls: list[int] = []

    def _fetch() -> str:
        calls.append(1)
        return "fetched"

    value = cache.cached("k", timedelta(hours=1), _fetch)

    assert value == "stored"
    assert calls == []


def test_a_hit_from_disk_is_read_once(tmp_path: Path) -> None:
    """Entries are held in memory, so a second look costs nothing."""
    directory = tmp_path / "cache"
    JsonDiskCache(directory).set("k", "stored", now=T0)

    cache = JsonDiskCache(directory)
    assert cache.get("k", HOUR, now=T0) == "stored"
    for entry in _entry_files(directory):
        entry.unlink()
    assert cache.get("k", HOUR, now=T0) == "stored"


def test_a_miss_fetches_and_stores(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")

    assert cache.cached("k", timedelta(hours=1), lambda: "fetched") == "fetched"
    assert cache.get("k", timedelta(hours=1)) == "fetched"


def test_a_failed_fetch_is_not_cached_as_though_it_were_an_answer(tmp_path: Path) -> None:
    """Otherwise the next caller reads the outage back as data."""
    cache = JsonDiskCache(tmp_path / "cache")

    def _boom() -> str:
        raise RuntimeError("platform down")

    with pytest.raises(RuntimeError):
        cache.cached("k", timedelta(hours=1), _boom)

    assert cache.get("k", timedelta(hours=1)) is None
