"""One JSON cache on disk, shared by every platform this app reads from.

The platforms differ in transport — two are plain public JSON, one is behind a
vendor SDK, one is a stats endpoint that rate-limits aggressively — but they
want the same thing from a cache: keep the last answer, and say when it stopped
being true. So the store is shared and only the *freshness rule* varies.

Most rules are a TTL, chosen from how fast the endpoint actually moves: Sleeper
asks callers to fetch its ~14MB catalog at most once a day, and a finished
season never changes again. Some are not expressible as a duration at all —
basketball's game log is good until the next game tips off, which is a moment
rather than an interval — so a rule is a predicate over when the entry was
stored, and `within` is the common case of one.

A cache is a **directory** and each key is its own file inside it. The
alternative, one document holding every entry, makes storing the smallest value
cost a rewrite of the largest: a trimmed player catalog is megabytes sitting
beside a scoreboard of a few kilobytes, and every write re-encoded the lot.
Per-key files also mean reading one entry never parses the others, and two
writers only collide when they are storing the same key.

Every write goes to a temporary file that is then renamed over the target, so a
process killed mid-write leaves the previous entry intact rather than a
half-written one. Nothing here is precious — the truth lives at the platform,
and a lost or unreadable entry costs one refetch — but a cache that corrupts
itself on Ctrl-C makes the next run slow for no reason.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

Freshness = Callable[[datetime, datetime], bool]
"""Given when an entry was stored and what time it is now, is it still good?"""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SLUG_LIMIT = 60
"""Long enough to recognise an entry by eye, short enough to stay inside the
path limits Windows still enforces once a deep repo path is prefixed."""


def within(ttl: timedelta) -> Freshness:
    """The common rule: good for a fixed interval after it was stored."""
    return lambda stored_at, now: now - stored_at <= ttl


def _rule(freshness: timedelta | Freshness) -> Freshness:
    """Accept a bare TTL wherever a rule is asked for, since most are one."""
    return within(freshness) if isinstance(freshness, timedelta) else freshness


def _filename(key: str) -> str:
    """A portable filename for `key`, unique to the exact key.

    The digest does the work; the slug is only a label, so that a human looking
    in the directory can tell `players_nfl` from a mini-league table. Keys carry
    what filenames cannot — the dots in a Yahoo league key, the spaces and
    punctuation of a player search, and case that macOS and Windows fold
    together — so correctness rests on the digest alone.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    slug = _UNSAFE.sub("-", key)[:_SLUG_LIMIT].strip("-.")
    return f"{slug}-{digest}.json" if slug else f"{digest}.json"


class JsonDiskCache:
    """Namespaced JSON values on disk, one file per key, each with its own rule."""

    def __init__(self, path: Path) -> None:
        """`path` is the directory the entries live in; it is created on write."""
        self._dir = path
        self._entries: dict[str, dict[str, Any]] = {}

    def _read(self, key: str) -> dict[str, Any] | None:
        """The stored envelope for `key`, from memory or else from its own file.

        Entries are held once read, so a second look at the same key costs
        nothing without loading the whole directory up front.
        """
        if key in self._entries:
            return self._entries[key]
        path = self._dir / _filename(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning(f"Discarding unreadable cache entry {path}: {e}")
            return None
        if not isinstance(raw, dict) or "stored_at" not in raw:
            return None
        self._entries[key] = raw
        return raw

    def _write(self, key: str, entry: dict[str, Any]) -> None:
        """Replace `key`'s file atomically.

        The temporary file is made in the destination directory rather than the
        system's: `os.replace` is only atomic within a single filesystem, and
        the temp directory is routinely a different one.
        """
        path = self._dir / _filename(key)
        temp: Path | None = None
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(dir=self._dir, prefix=".tmp-")
            temp = Path(name)
            with os.fdopen(handle, "w", encoding="utf-8") as f:
                json.dump(entry, f)
            os.replace(temp, path)
            temp = None
        except OSError as e:
            # Best effort: a cache we cannot persist still works for this run.
            logger.warning(f"Could not write cache entry {path}: {e}")
        finally:
            # Also covers a value that turned out not to be serialisable, which
            # is a bug worth raising but not worth leaving a stray file over.
            if temp is not None:
                temp.unlink(missing_ok=True)

    def get(self, key: str, freshness: timedelta | Freshness, now: datetime | None = None) -> Any | None:
        """Return the cached value for `key`, or None if absent or stale.

        `freshness` is a TTL for the usual case, or a predicate for a rule a
        duration cannot express.
        """
        entry = self._read(key)
        if entry is None:
            return None
        try:
            stored_at = datetime.fromisoformat(entry["stored_at"])
        except TypeError, ValueError:
            return None
        if stored_at.tzinfo is None:
            return None  # no zone, so it cannot be placed on a timeline
        moment = now or datetime.now(UTC)
        if not _rule(freshness)(stored_at, moment):
            return None
        return entry.get("value")

    def set(self, key: str, value: Any, now: datetime | None = None) -> None:
        """Store `value` under `key` and persist it."""
        stored_at = (now or datetime.now(UTC)).isoformat()
        entry = {"stored_at": stored_at, "value": value}
        self._entries[key] = entry
        self._write(key, entry)

    def cached(
        self,
        key: str,
        freshness: timedelta | Freshness,
        fetch: Callable[[], T],
        now: datetime | None = None,
    ) -> T:
        """The stored value for `key`, calling `fetch` only when it is stale.

        The read-through every platform wants, in one place: a hit never
        touches the network, and a miss stores what it fetched. A fetch that
        raises propagates rather than caching a failure as though it were an
        answer.
        """
        hit = self.get(key, freshness, now=now)
        if hit is not None:
            return hit
        value = fetch()
        self.set(key, value, now=now)
        return value

    def clear(self) -> None:
        """Forget every entry, in memory and on disk.

        Only files this cache could have written are removed, never the
        directory itself — a misconfigured path should cost nothing, and
        deleting a tree because a setting pointed somewhere unexpected is not a
        risk a cache needs to take.
        """
        self._entries = {}
        try:
            stale = list(self._dir.glob("*.json"))
        except OSError:
            return
        for entry in stale:
            try:
                entry.unlink()
            except OSError as e:
                logger.warning(f"Could not remove cache entry {entry}: {e}")
