"""One cache on disk, the store every platform client and kept answer shares.

The platforms differ in transport — three are plain public JSON, one is behind
a vendor SDK — but they want the same thing from a cache: keep the last answer,
and say when it stopped being true. Each read says how old an entry may be, a
TTL chosen from how fast that endpoint actually moves: Sleeper asks callers to
fetch its ~14MB catalog at most once a day, while a live score is stale in
minutes.

A cache is a **directory** holding one SQLite database, `cache.sqlite3`, with a
row per key: the value as zlib-compressed JSON and the aware UTC instant it was
stored. One database per directory rather than one for the app, so each setting
that moves a cache still moves all of it, and a platform's megabytes of churn
never share a file — or a corruption — with the manager's kept answers.

SQLite gives what a file per key had to build by hand, and what it could not:
an upsert is atomic, so a process killed mid-write leaves the previous entry
rather than half of one; storing the smallest value never rewrites the largest;
and writes from several threads or processes are serialised by the database,
WAL letting readers go on meanwhile. Compression makes the store about seven
times smaller than the JSON it holds, and costs a read about a tenth of its
parse.

Each thread reads through a connection of its own, because a web server reads
from several, and this instance's writes go through one lock so they queue here
rather than spin on the database's. What has been read is held in memory, so a
second look at a key costs nothing.

A directory the JSON-file-per-key cache wrote is adopted rather than ignored:
its files are named by a digest of the key, which cannot be read back to one,
so an entry moves into the database the first time its key is looked up, keeping
the time it was stored. That matters for what is not a cache at all — kept
answers, dismissed to-do items, a captured Yahoo sync — and costs a platform
cache nothing it would not have refetched. `clear` removes what was never adopted.
"""

import hashlib
import json
import logging
import re
import sqlite3
import threading
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DATABASE = "cache.sqlite3"
"""The database each cache directory holds."""

BUSY_TIMEOUT = timedelta(seconds=10)
"""How long a write waits on another process's before giving up and keeping the value in memory."""

COMPRESSION_LEVEL = 1
"""zlib's fastest: already about 7x smaller than the JSON on real caches, where its default
level saves another quarter for well over twice the time spent on every write."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    stored_at TEXT NOT NULL
)
"""

_UPSERT = """
INSERT INTO entries (key, value, stored_at) VALUES (?, ?, ?)
ON CONFLICT (key) DO UPDATE SET value = excluded.value, stored_at = excluded.stored_at
"""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SLUG_LIMIT = 60


def _legacy_filename(key: str) -> str:
    """The file the JSON-file-per-key cache kept `key` in: a slug to read by eye, a digest to be unique."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    slug = _UNSAFE.sub("-", key)[:_SLUG_LIMIT].strip("-.")
    return f"{slug}-{digest}.json" if slug else f"{digest}.json"


@dataclass(frozen=True)
class Hit:
    """A value the cache holds within its TTL.

    Its own type because the value may be null, and a stored null is an answer
    like any other: an endpoint that answered null is not asked again until the
    entry expires. `stored_at` is when it was written, so a value moved to
    another key can keep its age rather than start a fresh one.
    """

    value: Any
    stored_at: datetime


def _instant(text: object) -> datetime | None:
    """A stored timestamp as an aware instant, or None where it cannot be placed on a timeline."""
    if not isinstance(text, str):
        return None
    try:
        stored_at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stored_at if stored_at.tzinfo is not None else None


def _open(path: Path) -> sqlite3.Connection:
    """A connection to the database at `path` in WAL mode, creating its table on first use.

    Opened with `check_same_thread=False` though only one thread uses it, so that
    `_Connection` may close it from whichever thread collects it.
    """
    db = sqlite3.connect(path, timeout=BUSY_TIMEOUT.total_seconds(), isolation_level=None, check_same_thread=False)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute(_SCHEMA)
    except sqlite3.Error:
        db.close()
        raise
    return db


class _Connection:
    """One thread's connection, closed when the thread or the cache that opened it goes.

    Closed explicitly rather than left to the collector, which warns about an
    unclosed connection.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __del__(self) -> None:
        self.db.close()


class DiskCache:
    """Namespaced JSON values on disk, one SQLite database per directory."""

    def __init__(self, path: Path) -> None:
        """`path` is the directory the database lives in; it is created on write."""
        self._dir = path
        self._db = path / DATABASE
        self._entries: dict[str, Hit] = {}
        self._local = threading.local()
        self._write_lock = threading.Lock()

    def _connection(self, *, create: bool) -> sqlite3.Connection | None:
        """This thread's connection, or None where there is no database to read or none can be made.

        A read never creates the database: a first run looks before anything
        has been written, and a misconfigured path should not sprout a file.
        """
        held: _Connection | None = getattr(self._local, "connection", None)
        if held is not None:
            return held.db
        if not create and not self._db.exists():
            return None
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            held = _Connection(_open(self._db))
        except (OSError, sqlite3.Error) as e:
            logger.warning(f"Could not open cache database {self._db}: {e}")
            return None
        self._local.connection = held
        return held.db

    def _load(self, key: str) -> Hit | None:
        """What the database holds for `key`, adopting a file the old cache left for it."""
        row: tuple[object, object] | None = None
        db = self._connection(create=False)
        if db is not None:
            try:
                row = db.execute("SELECT value, stored_at FROM entries WHERE key = ?", (key,)).fetchone()
            except sqlite3.Error as e:
                logger.warning(f"Could not read cache entry {key!r} from {self._db}: {e}")
        if row is None:
            return self._adopt(key)
        blob, stored = row
        stored_at = _instant(stored)
        try:
            if stored_at is None or not isinstance(blob, bytes):
                raise ValueError("not an entry this cache wrote")
            return Hit(json.loads(zlib.decompress(blob)), stored_at)
        except (zlib.error, ValueError) as e:
            logger.warning(f"Discarding unreadable cache entry {key!r} in {self._db}: {e}")
            return None

    def _adopt(self, key: str) -> Hit | None:
        """The entry the JSON-file-per-key cache kept for `key`, moved into the database.

        The file goes only once the row is written, so a database that cannot
        be written loses nothing; one that cannot be read is left for `clear`.
        """
        path = self._dir / _legacy_filename(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning(f"Discarding unreadable cache entry {path}: {e}")
            return None
        if not isinstance(raw, dict) or "value" not in raw or (stored_at := _instant(raw.get("stored_at"))) is None:
            return None
        if self._write(key, raw["value"], stored_at):
            path.unlink(missing_ok=True)
        return Hit(raw["value"], stored_at)

    def _write(self, key: str, value: Any, stored_at: datetime) -> bool:
        """Upsert `key`'s row; whether it was persisted.

        Serialised before the database is touched, so a value that is not JSON
        raises without leaving a file behind.
        """
        blob = zlib.compress(json.dumps(value).encode("utf-8"), COMPRESSION_LEVEL)
        db = self._connection(create=True)
        if db is None:
            return False
        try:
            with self._write_lock:
                db.execute(_UPSERT, (key, blob, stored_at.astimezone(UTC).isoformat()))
        except sqlite3.Error as e:
            # Best effort: a cache we cannot persist still works for this run.
            logger.warning(f"Could not write cache entry {key!r} to {self._db}: {e}")
            return False
        return True

    def lookup(self, key: str, ttl: timedelta, now: datetime | None = None) -> Hit | None:
        """What is stored for `key` within `ttl` of `now`, or None if absent or stale — never for a stored null."""
        hit = self._entries.get(key)
        if hit is None:
            hit = self._load(key)
            if hit is None:
                return None
            self._entries[key] = hit
        if (now or datetime.now(UTC)) - hit.stored_at > ttl:
            return None
        return hit

    def get(self, key: str, ttl: timedelta, now: datetime | None = None) -> Any | None:
        """The value stored for `key` within `ttl`, or None.

        None also when the value stored is null; a caller that must tell the
        two apart — anything deciding whether to fetch — uses `lookup`.
        """
        hit = self.lookup(key, ttl, now)
        return hit.value if hit is not None else None

    def set(self, key: str, value: Any, now: datetime | None = None) -> None:
        """Store `value` under `key` and persist it."""
        stored_at = (now or datetime.now(UTC)).astimezone(UTC)
        self._write(key, value, stored_at)
        self._entries[key] = Hit(value, stored_at)

    def cached(self, key: str, ttl: timedelta, fetch: Callable[[], T], now: datetime | None = None) -> T:
        """The stored value for `key`, calling `fetch` only when it is stale.

        The read-through every platform wants, in one place: a hit never
        touches the network, and a miss stores what it fetched. A fetch that
        raises propagates rather than caching a failure as though it were an
        answer. A stored null is a hit, as `Hit` says.
        """
        hit = self.lookup(key, ttl, now)
        if hit is not None:
            return hit.value
        value = fetch()
        self.set(key, value, now=now)
        return value

    def clear(self) -> None:
        """Forget every entry, in memory and on disk.

        The rows go and the database stays, with any file the old cache left
        that was never adopted — and nothing else, never the directory itself:
        a misconfigured path should cost nothing, and deleting a tree because a
        setting pointed somewhere unexpected is not a risk a cache needs to take.
        """
        self._entries = {}
        db = self._connection(create=False)
        if db is not None:
            try:
                with self._write_lock:
                    db.execute("DELETE FROM entries")
            except sqlite3.Error as e:
                logger.warning(f"Could not clear cache database {self._db}: {e}")
        try:
            stale = list(self._dir.glob("*.json"))
        except OSError:
            return
        for entry in stale:
            try:
                entry.unlink()
            except OSError as e:
                logger.warning(f"Could not remove cache entry {entry}: {e}")
