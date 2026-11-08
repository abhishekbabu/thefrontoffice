"""Cached, retried access to a public JSON API, and the parallel cached fetch every platform shares.

Sleeper, ESPN and the Fantasy Premier League game are all open and read-only:
no OAuth, no key, plain GETs whose only real obligations are politeness about
request volume and a second attempt when a connection stalls. That is the whole
of what they share, so it is a collaborator a client holds rather than a base
class it inherits — the Yahoo client reaches its platform through a vendor SDK
and has no GET of its own to share, though it fetches in parallel through
`fetch_many` like the rest.

Each caller supplies its own domain error, because a failure has to surface as
the error that platform's adapter already raises. The retry policy arrives from
the composition root.
"""

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import requests

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy, outage
from thefrontoffice.domain.errors import FrontOfficeError, PlatformUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
MAX_PARALLEL_REQUESTS = 8
"""Enough to collapse a season of weekly requests into one wait, well inside
what these platforms ask for — Sleeper documents 1000 a minute."""


@dataclass
class Batch[K, V]:
    """What a parallel fetch found: every value it has, and why each missing one is missing."""

    values: dict[K, V] = field(default_factory=dict)
    failures: dict[K, FrontOfficeError] = field(default_factory=dict)

    def value(self, key: K) -> V:
        """The value under `key`, raising why it would not load where it did not."""
        if key in self.failures:
            raise self.failures[key]
        return self.values[key]

    def rekeyed[N](self, keys: Mapping[N, K]) -> Batch[N, V]:
        """The same batch under the caller's own keys — a week number rather than a cache key."""
        return Batch(
            values={new: self.values[old] for new, old in keys.items() if old in self.values},
            failures={new: self.failures[old] for new, old in keys.items() if old in self.failures},
        )


def fetch_many(cache: JsonDiskCache, fetches: Mapping[str, Callable[[], Any]], ttl: timedelta) -> Batch[str, Any]:
    """Each key's cached value, fetching only the misses and those in parallel.

    A season of weekly matchups is eighteen independent requests, and run one
    after another they are most of the wait on a page that is otherwise
    instant. Only the fetching is concurrent: what is stored is stored on this
    thread, because the cache holds what it has read in memory and that is not
    safe to write from several threads.

    A fetch that fails with a domain error is reported in `failures` rather
    than failing the batch, so the caller decides whether a hole is tolerable.
    Anything else is a bug and propagates.
    """
    batch: Batch[str, Any] = Batch()
    misses: dict[str, Callable[[], Any]] = {}
    for key, fetch in fetches.items():
        hit = cache.lookup(key, ttl)
        if hit is None:
            misses[key] = fetch
        else:
            batch.values[key] = hit.value
    if not misses:
        return batch

    with ThreadPoolExecutor(max_workers=min(len(misses), MAX_PARALLEL_REQUESTS)) as pool:
        futures = {key: pool.submit(fetch) for key, fetch in misses.items()}
        for key, future in futures.items():
            try:
                value = future.result()
            except FrontOfficeError as e:
                batch.failures[key] = e
                continue
            cache.set(key, value)
            batch.values[key] = value
    return batch


class JsonApiClient:
    """GETs against one public JSON API, retried and cached on disk."""

    def __init__(
        self,
        *,
        name: str,
        cache: JsonDiskCache,
        retry: RetryPolicy,
        error: type[FrontOfficeError],
        unavailable: type[PlatformUnavailableError],
        session: Any = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Args:
            name: the platform, for log lines and error messages.
            error: the domain error a failed request is translated into.
            unavailable: the one raised instead when the platform itself is down —
                a 5xx, a timeout, a connection that never opened — so the
                message can say "try again later" rather than "something is wrong".
        """
        self._name = name
        self._cache = cache
        self._retry = retry
        self._error = error
        self._unavailable = unavailable
        self._session = session or requests.Session()
        self._timeout = timeout

    def get(self, url: str, timeout: int | None = None) -> Any:
        """One GET, retried on transient failures, raising a domain error otherwise."""

        def _request() -> Any:
            response = self._session.get(url, timeout=timeout or self._timeout)
            response.raise_for_status()
            return response.json()

        try:
            return self._retry.call(_request)
        except Exception as e:
            logger.error(f"{self._name} request failed ({url}): {e}")
            down = outage(e)
            if down:
                raise self._unavailable(down) from e
            raise self._error(f"{self._name} request failed: {e}") from e

    def cached(
        self,
        key: str,
        url: str,
        ttl: timedelta,
        timeout: int | None = None,
        keep: Callable[[Any], Any] | None = None,
    ) -> Any:
        """The cached value for `key`, fetching and storing it when stale or absent.

        `keep` trims a response before it is stored, for an endpoint that
        answers megabytes of which a handful of fields are ever read: what is
        cached is then what is kept, not re-parsed from the whole on every read.
        """
        trim = keep or (lambda raw: raw)
        return self._cache.cached(key, ttl, lambda: trim(self.get(url, timeout=timeout)))

    def cached_many(self, urls: dict[str, str], ttl: timedelta) -> Batch[str, Any]:
        """Several cached GETs at once, fetching only the misses and in parallel.

        A request that fails is reported in the batch's `failures` rather than
        failing the rest, and logged here. Whether a hole is tolerable is the
        caller's to say: a week that would not load is not a week with nothing
        in it, so the caller has to be told which one it was.
        """
        batch = fetch_many(self._cache, {key: (lambda url=url: self.get(url)) for key, url in urls.items()}, ttl)
        for key, error in batch.failures.items():
            logger.warning(f"{self._name} batch missing {key}: {error}")
        return batch
