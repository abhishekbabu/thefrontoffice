"""Tests for the shared disk cache.

The store every platform reads through, so four things matter: what it keeps,
the age past which what it kept stops being returned, that it survives damage
and threads, and that what the JSON-file-per-key cache before it kept — kept
answers among it — is not lost to the move.
"""

import json
import logging
import sqlite3
import threading
import zlib
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from support.cache import stored_text
from support.logs import capture_logs

from thefrontoffice.adapters.outbound.cache import DATABASE, DiskCache, _legacy_filename

HOUR = timedelta(hours=1)
THREADS = 32
ATTEMPTS = 50
"""A race lost a few times in a hundred on macOS and nearly always on Windows needs a few goes to show."""
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _execute(directory: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    """Run `sql` on the database in `directory` from outside the cache, as another process would."""
    with closing(sqlite3.connect(directory / DATABASE)) as db:
        rows = db.execute(sql, params).fetchall()
        db.commit()
    return rows


def _legacy(directory: Path, key: str, entry: object) -> Path:
    """Write `entry` where the JSON-file-per-key cache kept `key`, named as it named it."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _legacy_filename(key)
    path.write_text(json.dumps(entry), encoding="utf-8")
    return path


def test_value_persists_across_instances(tmp_path: Path) -> None:
    DiskCache(tmp_path / "cache").set("k", [1, 2], now=T0)
    assert DiskCache(tmp_path / "cache").get("k", HOUR, now=T0) == [1, 2]


def test_missing_directory_is_not_an_error_and_a_read_creates_nothing(tmp_path: Path) -> None:
    """A first run reads before anything has ever been written."""
    assert DiskCache(tmp_path / "never-created").get("k", HOUR) is None
    assert not (tmp_path / "never-created").exists()


def test_expired_value_is_none(tmp_path: Path) -> None:
    c = DiskCache(tmp_path / "cache")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0 + timedelta(minutes=59)) == "v"
    assert c.get("k", HOUR, now=T0 + timedelta(hours=1, seconds=1)) is None


def test_the_age_survives_a_reopen_whatever_zone_it_was_stored_in(tmp_path: Path) -> None:
    """Stored as UTC, so a value written with an offset expires at the same instant."""
    pacific = T0.astimezone(timezone(timedelta(hours=-7)))
    DiskCache(tmp_path / "cache").set("k", "v", now=pacific)

    hit = DiskCache(tmp_path / "cache").lookup("k", HOUR, now=T0)

    assert hit is not None and hit.stored_at == T0
    assert DiskCache(tmp_path / "cache").get("k", HOUR, now=T0 + timedelta(hours=1, seconds=1)) is None


def test_a_rewrite_replaces_the_value_and_its_age(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    DiskCache(directory).set("k", "old", now=T0)
    DiskCache(directory).set("k", "new", now=T0 + HOUR)

    assert DiskCache(directory).get("k", HOUR, now=T0 + timedelta(hours=1, minutes=30)) == "new"


def test_values_are_stored_compressed(tmp_path: Path) -> None:
    """A trimmed player catalog is megabytes of repetitive JSON."""
    directory = tmp_path / "cache"
    catalog = {str(n): {"position": "WR", "team": "KC", "status": "Active"} for n in range(2000)}
    DiskCache(directory).set("players_nfl", catalog, now=T0)

    ((size,),) = _execute(directory, "SELECT length(value) FROM entries")
    assert isinstance(size, int) and size * 5 < len(json.dumps(catalog))
    assert '"position": "WR"' in stored_text(directory)


# ── durability ──────────────────────────────────────────────────────────


def test_an_unserialisable_value_raises_and_leaves_nothing_behind(tmp_path: Path) -> None:
    """A bug worth surfacing, but not worth a database it never needed."""
    directory = tmp_path / "cache"
    c = DiskCache(directory)

    with pytest.raises(TypeError):
        c.set("k", {1, 2, 3}, now=T0)

    assert not directory.exists()
    assert c.get("k", HOUR, now=T0) is None


@pytest.mark.parametrize(
    ("value", "stored_at"),
    [
        (b"not zlib", T0.isoformat()),
        (zlib.compress(b"hello"), T0.isoformat()),  # compressed, but not JSON
        ("text, not a blob", T0.isoformat()),
        (zlib.compress(b'"v"'), "2026-09-01T12:00:00"),  # without a zone it cannot be placed on a timeline
        (zlib.compress(b'"v"'), "whenever"),
    ],
    ids=["not-compressed", "not-json", "not-a-blob", "naive-timestamp", "unparseable-timestamp"],
)
def test_a_row_the_cache_cannot_read_is_discarded_not_fatal(tmp_path: Path, value: object, stored_at: str) -> None:
    directory = tmp_path / "cache"
    c = DiskCache(directory)
    c.set("good", "kept", now=T0)
    _execute(directory, "INSERT INTO entries VALUES ('bad', ?, ?)", value, stored_at)

    fresh = DiskCache(directory)
    assert fresh.get("bad", HOUR, now=T0) is None
    assert fresh.get("good", HOUR, now=T0) == "kept"
    fresh.set("bad", "v", now=T0)
    assert DiskCache(directory).get("bad", HOUR, now=T0) == "v"


def test_a_file_that_is_not_a_database_costs_persistence_not_the_run(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    directory.mkdir()
    (directory / DATABASE).write_text("not a database", encoding="utf-8")

    c = DiskCache(directory)
    assert c.get("k", HOUR, now=T0) is None
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"
    c.clear()


def test_a_database_damaged_after_it_was_prepared_costs_persistence_not_the_run(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    DiskCache(directory).set("k", "v", now=T0)
    for path in directory.iterdir():
        path.unlink()
    (directory / DATABASE).write_text("not a database", encoding="utf-8")

    with capture_logs("thefrontoffice.adapters.outbound.cache", logging.WARNING) as logs:
        c = DiskCache(directory)
        c.set("k2", "v2", now=T0)

    assert "Could not open cache database" in logs.text
    assert c.get("k2", HOUR, now=T0) == "v2"


def test_a_database_another_process_has_dropped_from_is_a_miss(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    c = DiskCache(directory)
    c.set("k", "v", now=T0)
    _execute(directory, "DROP TABLE entries")

    assert c.get("other", HOUR, now=T0) is None
    c.set("k2", "v", now=T0)
    assert c.get("k2", HOUR, now=T0) == "v"
    c.clear()


def test_unwritable_path_does_not_raise(tmp_path: Path) -> None:
    """A cache we cannot persist still has to work for this run."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    c = DiskCache(blocker / "sub")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"


def test_writes_from_many_threads_all_land(tmp_path: Path) -> None:
    """The web server reads and writes from several threads at once, each opening its first connection together.

    Every thread's first connection used to switch the new database to WAL at
    once, which SQLite refuses rather than queues: the losers kept their value
    in memory only, and on Windows that was nearly all of them.
    """
    with capture_logs("thefrontoffice.adapters.outbound.cache", logging.WARNING) as logs:
        landed = [_store_together(tmp_path / f"cache{attempt}") for attempt in range(ATTEMPTS)]

    assert logs.text == ""
    assert landed == [list(range(THREADS))] * ATTEMPTS


def _store_together(directory: Path) -> list[object]:
    """`THREADS` threads each storing one key in a new cache at the same instant; what a fresh one reads back."""
    c = DiskCache(directory)
    start = threading.Barrier(THREADS)

    def _store(n: int) -> None:
        start.wait()
        c.set(f"k{n}", n, now=T0)

    threads = [threading.Thread(target=_store, args=(n,)) for n in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    fresh = DiskCache(directory)
    return [fresh.get(f"k{n}", HOUR, now=T0) for n in range(THREADS)]


def test_a_write_that_cannot_persist_says_so(tmp_path: Path) -> None:
    """Kept in memory for the run, but never silently: a dropped write is a warning naming the key."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with capture_logs("thefrontoffice.adapters.outbound.cache", logging.WARNING) as logs:
        DiskCache(blocker / "sub").set("k", "v", now=T0)

    assert "Could not open cache database" in logs.text


def test_a_database_another_process_holds_is_waited_for_not_dropped(tmp_path: Path) -> None:
    """Another process preparing or writing the same new database is waited on, not taken for an unwritable one."""
    directory = tmp_path / "cache"
    directory.mkdir()
    holder = sqlite3.connect(directory / DATABASE, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")
    release = threading.Timer(0.2, holder.close)
    release.start()

    with capture_logs("thefrontoffice.adapters.outbound.cache", logging.WARNING) as logs:
        DiskCache(directory).set("k", "v", now=T0)
    release.join()

    assert logs.text == ""
    assert DiskCache(directory).get("k", HOUR, now=T0) == "v"


def test_a_database_deleted_under_a_running_cache_is_made_again(tmp_path: Path) -> None:
    """`just clean-data` while the server runs: the next connection recreates the table rather than failing."""
    directory = tmp_path / "cache"
    DiskCache(directory).set("k", "v", now=T0)
    for path in directory.iterdir():
        path.unlink()

    def _store() -> None:
        DiskCache(directory).set("k2", "v2", now=T0)

    thread = threading.Thread(target=_store)
    thread.start()
    thread.join()

    assert DiskCache(directory).get("k2", HOUR, now=T0) == "v2"


def test_clear_empties_the_cache(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    c = DiskCache(directory)
    c.set("k", "v", now=T0)
    c.clear()
    assert c.get("k", HOUR, now=T0) is None
    assert DiskCache(directory).get("k", HOUR, now=T0) is None


def test_clear_leaves_the_directory_and_anything_else_in_it(tmp_path: Path) -> None:
    """A misconfigured path should cost nothing it did not put there."""
    directory = tmp_path / "cache"
    c = DiskCache(directory)
    c.set("k", "v", now=T0)
    stranger = directory / "not-ours.txt"
    stranger.write_text("keep me", encoding="utf-8")

    c.clear()

    assert directory.exists()
    assert stranger.read_text(encoding="utf-8") == "keep me"


def test_clear_on_a_cache_never_written_is_harmless(tmp_path: Path) -> None:
    DiskCache(tmp_path / "never-created").clear()
    assert not (tmp_path / "never-created").exists()


# ── adopting the JSON-file-per-key cache ────────────────────────────────


def test_an_entry_the_old_cache_kept_is_adopted_with_its_age(tmp_path: Path) -> None:
    """Kept answers and dismissed to-do items are the manager's own, not a cache to refetch."""
    directory = tmp_path / "cache"
    old = _legacy(directory, "scout:nba-yahoo:466.l.9", {"stored_at": T0.isoformat(), "value": {"kept": True}})

    hit = DiskCache(directory).lookup("scout:nba-yahoo:466.l.9", HOUR, now=T0 + timedelta(minutes=5))

    assert hit is not None and hit.value == {"kept": True} and hit.stored_at == T0
    assert not old.exists()
    assert DiskCache(directory).get("scout:nba-yahoo:466.l.9", HOUR, now=T0) == {"kept": True}


def test_an_adopted_entry_that_is_already_stale_is_kept_for_a_longer_look(tmp_path: Path) -> None:
    """The Yahoo scoreboard falls back to its stored copy, however old, when a refresh fails."""
    directory = tmp_path / "cache"
    _legacy(directory, "scoreboard", {"stored_at": T0.isoformat(), "value": "last known"})
    c = DiskCache(directory)

    assert c.lookup("scoreboard", HOUR, now=T0 + timedelta(days=2)) is None
    assert DiskCache(directory).get("scoreboard", timedelta.max, now=T0 + timedelta(days=2)) == "last known"


def test_an_adopted_null_is_still_a_hit(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _legacy(directory, "k", {"stored_at": T0.isoformat(), "value": None})

    hit = DiskCache(directory).lookup("k", HOUR, now=T0)

    assert hit is not None and hit.value is None


@pytest.mark.parametrize(
    "entry",
    [
        [1, 2, 3],
        {"value": "v"},
        {"stored_at": "2026-09-01T12:00:00", "value": "v"},
        {"stored_at": "whenever", "value": "v"},
        {"stored_at": 1234, "value": "v"},
    ],
    ids=["not-an-envelope", "no-timestamp", "naive-timestamp", "unparseable-timestamp", "non-string-timestamp"],
)
def test_an_old_entry_that_cannot_be_dated_is_not_adopted(tmp_path: Path, entry: object) -> None:
    directory = tmp_path / "cache"
    _legacy(directory, "k", entry)
    assert DiskCache(directory).get("k", HOUR, now=T0) is None


def test_an_unreadable_old_entry_is_a_miss_left_for_clear(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    path = _legacy(directory, "k", "ignored")
    path.write_text("{not json", encoding="utf-8")
    c = DiskCache(directory)

    assert c.get("k", HOUR, now=T0) is None
    assert path.exists()
    c.clear()
    assert not path.exists()


def test_an_old_entry_is_kept_on_disk_when_the_database_cannot_take_it(tmp_path: Path) -> None:
    """Nothing is deleted until it is somewhere else."""
    directory = tmp_path / "cache"
    path = _legacy(directory, "k", {"stored_at": T0.isoformat(), "value": "precious"})
    (directory / DATABASE).mkdir()  # where the database should be, something it cannot open

    assert DiskCache(directory).get("k", HOUR, now=T0) == "precious"
    assert path.exists()


def test_a_newer_row_wins_over_an_old_file(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    path = _legacy(directory, "k", {"stored_at": T0.isoformat(), "value": "old"})
    DiskCache(directory).set("k", "new", now=T0 + HOUR)

    assert DiskCache(directory).get("k", HOUR, now=T0 + HOUR) == "new"
    assert path.exists()  # never read, so never adopted: `clear` is what removes it


# ── read-through ────────────────────────────────────────────────────────


def test_a_hit_never_calls_the_fetch(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
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
    DiskCache(directory).set("k", "stored", now=T0)

    cache = DiskCache(directory)
    assert cache.get("k", HOUR, now=T0) == "stored"
    _execute(directory, "DELETE FROM entries")
    assert cache.get("k", HOUR, now=T0) == "stored"


def test_a_stored_null_is_a_hit_not_a_reason_to_fetch_again(tmp_path: Path) -> None:
    """An endpoint answering null is asked again when the entry expires, not on every read."""
    calls: list[int] = []

    def _fetch() -> None:
        calls.append(1)

    DiskCache(tmp_path / "cache").cached("k", HOUR, _fetch)
    DiskCache(tmp_path / "cache").cached("k", HOUR, _fetch)

    assert calls == [1]


def test_a_lookup_tells_a_stored_null_from_a_miss(tmp_path: Path) -> None:
    DiskCache(tmp_path / "cache").set("null", None, now=T0)
    cache = DiskCache(tmp_path / "cache")

    hit = cache.lookup("null", HOUR, now=T0)
    assert hit is not None and hit.value is None
    assert cache.lookup("absent", HOUR, now=T0) is None


def test_a_miss_fetches_and_stores(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")

    assert cache.cached("k", timedelta(hours=1), lambda: "fetched") == "fetched"
    assert cache.get("k", timedelta(hours=1)) == "fetched"


def test_a_failed_fetch_is_not_cached_as_though_it_were_an_answer(tmp_path: Path) -> None:
    """Otherwise the next caller reads the outage back as data."""
    cache = DiskCache(tmp_path / "cache")

    def _boom() -> str:
        raise RuntimeError("platform down")

    with pytest.raises(RuntimeError):
        cache.cached("k", timedelta(hours=1), _boom)

    assert cache.get("k", timedelta(hours=1)) is None
