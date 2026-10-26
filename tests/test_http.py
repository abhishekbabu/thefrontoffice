"""Tests for the JSON transport the public-API clients share."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pytest
import requests

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError, FPLUnavailableError
from thefrontoffice.adapters.outbound.platforms.http import JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import build_retry, is_transient
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError, SleeperUnavailableError
from thefrontoffice.domain.errors import PlatformUnavailableError

TTL = timedelta(hours=1)


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # A real Response carrying the status, which is all the retry and
            # outage checks read off a failure.
            failed = requests.Response()
            failed.status_code = self.status_code
            raise requests.exceptions.HTTPError(response=failed)

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, payload: Any = None, error: Exception | None = None, status: int = 200) -> None:
        self.payload = payload
        self.error = error
        self.status = status
        self.requests: list[str] = []
        self.timeouts: list[int] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requests.append(url)
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return FakeResponse(self.payload, self.status)


UNAVAILABLE: dict[type, type[PlatformUnavailableError]] = {
    SleeperAPIError: SleeperUnavailableError,
    FPLAPIError: FPLUnavailableError,
}


class Session(Protocol):
    """What the transport needs of a session: one GET."""

    def get(self, url: str, timeout: int = 0) -> FakeResponse: ...


def _client(
    tmp_path: Path, session: Session, error: type = SleeperAPIError, cache: JsonDiskCache | None = None
) -> JsonApiClient:
    return JsonApiClient(
        name="Test",
        cache=cache or JsonDiskCache(tmp_path / "cache"),
        # No real backoff; the hermetic suite must not spend seconds sleeping.
        retry=lambda: build_retry(attempts=2, multiplier=1, min_wait=0, max_wait=0, predicate=is_transient).copy(
            wait=lambda _: 0
        ),
        error=error,
        unavailable=UNAVAILABLE[error],
        session=session,
        timeout=11,
    )


def test_a_successful_get_returns_the_payload(tmp_path: Path) -> None:
    session = FakeSession({"ok": True})
    assert _client(tmp_path, session).get("https://example.test/a") == {"ok": True}
    assert session.timeouts == [11]


def test_a_call_can_override_the_default_timeout(tmp_path: Path) -> None:
    """The player catalog is far larger than anything else and needs longer."""
    session = FakeSession({})
    _client(tmp_path, session).get("https://example.test/big", timeout=90)
    assert session.timeouts == [90]


def test_a_failure_becomes_the_callers_domain_error(tmp_path: Path) -> None:
    session = FakeSession(status=404)
    with pytest.raises(FPLAPIError, match="Test request failed"):
        _client(tmp_path, session, error=FPLAPIError).get("https://example.test/a")


@pytest.mark.parametrize(
    "session",
    [
        FakeSession(status=503),
        FakeSession(error=requests.exceptions.Timeout()),
        FakeSession(error=requests.exceptions.ConnectionError("refused")),
    ],
    ids=["server-error", "timeout", "no-connection"],
)
def test_a_platform_that_is_down_says_to_wait(tmp_path: Path, session: FakeSession) -> None:
    """Still the platform's own error, so whatever carries on without it still catches it."""
    with pytest.raises(FPLUnavailableError) as raised:
        _client(tmp_path, session, error=FPLAPIError).get("https://example.test/a")

    assert isinstance(raised.value, FPLAPIError)
    assert raised.value.code == PlatformUnavailableError.code


def test_a_request_the_platform_turned_down_is_not_an_outage(tmp_path: Path) -> None:
    with pytest.raises(FPLAPIError) as raised:
        _client(tmp_path, FakeSession(status=404), error=FPLAPIError).get("https://example.test/a")

    assert not isinstance(raised.value, PlatformUnavailableError)


def test_each_caller_gets_its_own_error_type(tmp_path: Path) -> None:
    """One transport, two platforms — a failure must not surface as the wrong one."""
    session = FakeSession(error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(SleeperAPIError):
        _client(tmp_path, session, error=SleeperAPIError).get("https://example.test/a")


def test_a_transient_failure_is_retried(tmp_path: Path) -> None:
    session = FakeSession(error=requests.exceptions.Timeout())
    with pytest.raises(SleeperAPIError):
        _client(tmp_path, session).get("https://example.test/a")
    assert len(session.requests) == 2


def test_a_cached_value_is_served_without_a_second_request(tmp_path: Path) -> None:
    session = FakeSession({"n": 1})
    client = _client(tmp_path, session)
    assert client.cached("k", "https://example.test/a", TTL) == {"n": 1}
    assert client.cached("k", "https://example.test/a", TTL) == {"n": 1}
    assert len(session.requests) == 1


def test_an_expired_entry_is_refetched(tmp_path: Path) -> None:
    """The entry is aged explicitly rather than by writing it with a zero TTL.

    A zero TTL only expires once the clock has advanced, and Windows ticks at
    about 15ms — so a write and the read after it land on the same instant and
    the entry is served rather than refetched.
    """
    cache = JsonDiskCache(tmp_path / "cache")
    cache.set("k", {"n": 1}, now=datetime.now(UTC) - timedelta(hours=2))

    session = FakeSession({"n": 2})
    assert _client(tmp_path, session, cache=cache).cached("k", "https://example.test/a", TTL) == {"n": 2}
    assert len(session.requests) == 1


def test_a_caller_can_transform_before_storing(tmp_path: Path) -> None:
    """The catalog is trimmed on the way in, so it bypasses `cached`."""
    client = _client(tmp_path, FakeSession())
    assert client.cache_get("k", TTL) is None
    client.cache_set("k", {"trimmed": True})
    assert client.cache_get("k", TTL) == {"trimmed": True}


def test_a_stored_value_survives_a_new_client_on_the_same_file(tmp_path: Path) -> None:
    _client(tmp_path, FakeSession()).cache_set("k", [1, 2])
    assert _client(tmp_path, FakeSession()).cache_get("k", TTL) == [1, 2]


def test_the_cache_is_keyed_not_url_addressed(tmp_path: Path) -> None:
    """Two URLs under one key is how a paginated endpoint is folded together."""
    session = FakeSession({"n": 1})
    client = _client(tmp_path, session)
    client.cached("same", "https://example.test/a", TTL)
    client.cached("same", "https://example.test/b", TTL)
    assert session.requests == ["https://example.test/a"]


def test_a_cache_entry_stores_when_it_was_written(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeSession())
    client.cache_set("k", 1)
    assert client.cache_get("k", timedelta(seconds=1)) == 1
    stale = JsonDiskCache(tmp_path / "cache").get("k", timedelta(seconds=1), now=datetime.now(UTC) + TTL)
    assert stale is None


# ── batched reads ───────────────────────────────────────────────────────


class RoutedSession:
    """Answers by URL, and records which thread each request ran on."""

    def __init__(self, routes: dict[str, Any], failing: set[str] | None = None) -> None:
        self.routes = routes
        self.failing = failing or set()
        self.requests: list[str] = []
        self.threads: set[str] = set()

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        import threading
        import time

        self.threads.add(threading.current_thread().name)
        self.requests.append(url)
        if url in self.failing:
            raise requests.exceptions.ConnectionError("down")
        time.sleep(0.02)  # long enough that serial execution is distinguishable
        return FakeResponse(self.routes.get(url))


ROUTES = {f"https://example.test/{i}": {"week": i} for i in range(1, 6)}
URLS = {f"k{i}": f"https://example.test/{i}" for i in range(1, 6)}


def test_a_batch_returns_every_key(tmp_path: Path) -> None:
    session = RoutedSession(ROUTES)

    result = _client(tmp_path, session).cached_many(URLS, TTL)

    assert result == {f"k{i}": {"week": i} for i in range(1, 6)}


def test_a_batch_fetches_concurrently(tmp_path: Path) -> None:
    """Eighteen weeks run one after another are the whole wait on the page."""
    session = RoutedSession(ROUTES)

    _client(tmp_path, session).cached_many(URLS, TTL)

    assert len(session.threads) > 1, "requests ran on a single thread"


def test_a_batch_only_fetches_what_it_does_not_have(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    cache.set("k1", {"week": 1})
    cache.set("k2", {"week": 2})
    session = RoutedSession(ROUTES)

    result = _client(tmp_path, session, cache=cache).cached_many(URLS, TTL)

    assert sorted(session.requests) == [f"https://example.test/{i}" for i in (3, 4, 5)]
    assert result["k1"] == {"week": 1}


def test_a_fully_cached_batch_touches_the_network_at_all(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    for i in range(1, 6):
        cache.set(f"k{i}", {"week": i})
    session = RoutedSession(ROUTES)

    _client(tmp_path, session, cache=cache).cached_many(URLS, TTL)

    assert session.requests == []


def test_batch_writes_stay_on_the_calling_thread(tmp_path: Path) -> None:
    """The cache file is read-modify-written whole, so concurrent writes would
    clobber each other. Only the requests are allowed to fan out."""
    writes: set[str] = set()

    class Recording(JsonDiskCache):
        def set(self, key: str, value: Any, now: Any = None) -> None:
            import threading

            writes.add(threading.current_thread().name)
            super().set(key, value, now=now)

    session = RoutedSession(ROUTES)
    _client(tmp_path, session, cache=Recording(tmp_path / "c.json")).cached_many(URLS, TTL)

    assert len(writes) == 1


def test_one_failed_request_leaves_a_hole_rather_than_failing_the_batch(tmp_path: Path) -> None:
    """Seventeen weeks of a season is worth more than no season at all."""
    session = RoutedSession(ROUTES, failing={"https://example.test/3"})

    result = _client(tmp_path, session).cached_many(URLS, TTL)

    assert "k3" not in result
    assert sorted(result) == ["k1", "k2", "k4", "k5"]


def test_a_failed_request_is_not_stored_as_though_it_were_an_answer(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "cache")
    session = RoutedSession(ROUTES, failing={"https://example.test/3"})

    _client(tmp_path, session, cache=cache).cached_many(URLS, TTL)

    assert cache.get("k3", TTL) is None
