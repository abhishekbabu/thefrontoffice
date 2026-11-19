"""Tests for the request budget: the pace, the cap, the breaker, shared requests and background refreshes.

Time is a fake clock whose sleep moves it on, so a pace is measured in the
seconds it would have cost rather than waited out.
"""

import threading
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from support.http import http_error
from support.yahoo import FakeContext

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo.budget import (
    COOLDOWN,
    REFUSED_COOLDOWN,
    STRIKES,
    Breaker,
    Budget,
    BudgetedContext,
    Refresher,
    SingleFlight,
    Throttle,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooSessionExpiredError,
    YahooUnavailableError,
)

WAIT = 5
"""Seconds a test thread waits on another before calling it stuck."""


class Clock:
    """Monotonic seconds that only move when something sleeps or the test says so."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _limited(status: int, after: str = "") -> Exception:
    error = http_error(status)
    if after:
        assert error.response is not None
        error.response.headers["Retry-After"] = after
    return error


# ── the pace ────────────────────────────────────────────────────────────


def test_a_burst_goes_at_once_and_the_rest_at_the_rate() -> None:
    clock = Clock()
    throttle = Throttle(rate=2, burst=3, concurrency=1, clock=clock, sleep=clock.sleep)

    for _ in range(5):
        with throttle.slot():
            pass

    assert clock.slept == [0.5, 0.5]


def test_a_quiet_spell_refills_the_bucket_up_to_the_burst_and_no_further() -> None:
    clock = Clock()
    throttle = Throttle(rate=2, burst=2, concurrency=1, clock=clock, sleep=clock.sleep)
    for _ in range(2):
        with throttle.slot():
            pass

    clock.now += 60
    for _ in range(3):
        with throttle.slot():
            pass

    assert clock.slept == [0.5]


def test_no_more_than_the_cap_are_in_flight_at_once() -> None:
    throttle = Throttle(rate=1000, burst=1000, concurrency=2)
    inside, release = threading.Semaphore(0), threading.Event()
    most = [0]
    flying = [0]
    lock = threading.Lock()

    def request() -> None:
        with throttle.slot():
            with lock:
                flying[0] += 1
                most[0] = max(most[0], flying[0])
            inside.release()
            release.wait(WAIT)
            with lock:
                flying[0] -= 1

    threads = [threading.Thread(target=request) for _ in range(3)]
    for thread in threads:
        thread.start()
    assert inside.acquire(timeout=WAIT) and inside.acquire(timeout=WAIT)
    assert not inside.acquire(timeout=0.2)  # the third waits its turn
    release.set()
    for thread in threads:
        thread.join(WAIT)

    assert most[0] == 2


# ── the breaker ─────────────────────────────────────────────────────────


def test_the_breaker_opens_after_repeated_failures_and_closes_once_the_pause_is_over() -> None:
    clock = Clock()
    breaker = Breaker(clock=clock)
    for _ in range(STRIKES - 1):
        breaker.failed()
    breaker.check()

    breaker.failed()
    with pytest.raises(YahooUnavailableError):
        breaker.check()

    clock.now += COOLDOWN
    breaker.check()


def test_once_the_pause_is_over_the_first_failure_opens_it_again() -> None:
    clock = Clock()
    breaker = Breaker(clock=clock)
    for _ in range(STRIKES):
        breaker.failed()
    clock.now += COOLDOWN

    breaker.failed()

    with pytest.raises(YahooUnavailableError):
        breaker.check()


def test_a_success_wipes_the_count() -> None:
    breaker = Breaker(clock=Clock())
    for _ in range(STRIKES - 1):
        breaker.failed()

    breaker.succeeded()
    breaker.failed()

    breaker.check()


def test_a_named_pause_opens_the_breaker_for_exactly_that_long() -> None:
    clock = Clock()
    breaker = Breaker(clock=clock)

    breaker.failed(pause=30)

    clock.now += 29
    with pytest.raises(YahooUnavailableError):
        breaker.check()
    clock.now += 1
    breaker.check()


def test_a_refused_session_stops_every_request_with_the_session_error() -> None:
    """The remedy is a fresh cookie, so that is what every page says until the pause is over."""
    clock = Clock()
    breaker = Breaker(clock=clock)

    breaker.refused()

    with pytest.raises(YahooSessionExpiredError):
        breaker.check()
    clock.now += REFUSED_COOLDOWN
    breaker.check()


# ── shared requests ─────────────────────────────────────────────────────


def test_concurrent_asks_for_one_key_share_one_call() -> None:
    flights = SingleFlight()
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def slow() -> str:
        calls.append(1)
        started.set()
        release.wait(WAIT)
        return "answer"

    results: list[str] = []
    leader = threading.Thread(target=lambda: results.append(flights.share("k", slow)))
    leader.start()
    assert started.wait(WAIT)
    follower = threading.Thread(target=lambda: results.append(flights.share("k", slow)))
    follower.start()
    follower.join(0.2)  # parked on the leader's answer
    release.set()
    leader.join(WAIT)
    follower.join(WAIT)

    assert (results, len(calls)) == (["answer", "answer"], 1)


def test_a_shared_failure_reaches_every_asker_and_the_next_ask_tries_again() -> None:
    flights = SingleFlight()
    started, release = threading.Event(), threading.Event()

    def failing() -> str:
        started.set()
        release.wait(WAIT)
        raise YahooAPIError("down")

    errors: list[BaseException] = []

    def ask() -> None:
        try:
            flights.share("k", failing)
        except YahooAPIError as e:
            errors.append(e)

    leader = threading.Thread(target=ask)
    leader.start()
    assert started.wait(WAIT)
    follower = threading.Thread(target=ask)
    follower.start()
    follower.join(0.2)
    release.set()
    leader.join(WAIT)
    follower.join(WAIT)

    assert len(errors) == 2
    assert flights.share("k", lambda: "recovered") == "recovered"


# ── background refreshes ────────────────────────────────────────────────


def test_a_refresh_stores_what_it_fetched(tmp_path: Path) -> None:
    refresher = Refresher(lambda: DiskCache(tmp_path / "cache"))

    refresher.refresh("teams", lambda: "<fresh/>")
    refresher.settle()

    assert DiskCache(tmp_path / "cache").get("teams", timedelta(minutes=1)) == "<fresh/>"


def test_a_key_already_queued_is_not_queued_twice(tmp_path: Path) -> None:
    release = threading.Event()
    fetched: list[str] = []
    refresher = Refresher(lambda: DiskCache(tmp_path / "cache"))

    def slow(name: str) -> str:
        release.wait(WAIT)
        fetched.append(name)
        return name

    refresher.refresh("blocker", lambda: slow("blocker"))
    refresher.refresh("teams", lambda: slow("first"))
    refresher.refresh("teams", lambda: slow("second"))
    release.set()
    refresher.settle()

    assert fetched == ["blocker", "first"]


def test_a_full_queue_drops_the_refresh_rather_than_waiting(tmp_path: Path) -> None:
    started, release = threading.Event(), threading.Event()
    fetched: list[str] = []
    refresher = Refresher(lambda: DiskCache(tmp_path / "cache"), limit=1)

    def slow(name: str) -> str:
        started.set()
        release.wait(WAIT)
        fetched.append(name)
        return name

    refresher.refresh("running", lambda: slow("running"))
    assert started.wait(WAIT)  # off the queue and running, leaving room for one
    refresher.refresh("queued", lambda: slow("queued"))
    refresher.refresh("dropped", lambda: slow("dropped"))
    release.set()
    refresher.settle()

    assert fetched == ["running", "queued"]


def test_a_failed_refresh_leaves_the_stale_copy_standing(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.set("teams", "<stale/>")
    refresher = Refresher(lambda: DiskCache(tmp_path / "cache"))

    def down() -> str:
        raise YahooUnavailableError("it answered 503")

    refresher.refresh("teams", down)
    refresher.settle()

    assert DiskCache(tmp_path / "cache").get("teams", timedelta(days=1)) == "<stale/>"


def test_a_refresh_that_fails_unexpectedly_does_not_stop_the_next(tmp_path: Path) -> None:
    """One thread runs every refresh, so a bug in one must not end the rest for the process."""
    refresher = Refresher(lambda: DiskCache(tmp_path / "cache"))

    def broken() -> str:
        raise KeyError("bug")

    refresher.refresh("roster", broken)
    refresher.refresh("teams", lambda: "<fresh/>")
    settling = threading.Thread(target=refresher.settle, daemon=True)
    settling.start()
    settling.join(WAIT)  # a dead worker would leave the queue unsettled for good

    assert DiskCache(tmp_path / "cache").get("teams", timedelta(minutes=1)) == "<fresh/>"


# ── asking Yahoo within the budget ──────────────────────────────────────


def _budgeted(context: FakeContext, clock: Clock) -> BudgetedContext:
    limits = Budget(
        throttle=Throttle(rate=2, burst=1, concurrency=1, clock=clock, sleep=clock.sleep), breaker=Breaker(clock=clock)
    )
    return BudgetedContext(context, limits)


def test_requests_are_paced_through_the_budget() -> None:
    clock = Clock()
    context = FakeContext("<fantasy_content/>")
    budgeted = _budgeted(context, clock)

    for week in (1, 2, 3):
        assert budgeted.make_request(f"scoreboard;week={week}", "466.l.1") == "<fantasy_content/>"

    assert context.requests == [(f"scoreboard;week={week}", "466.l.1") for week in (1, 2, 3)]
    assert clock.slept == [0.5, 0.5]


def test_repeated_outages_stop_requests_reaching_yahoo() -> None:
    clock = Clock()
    context = FakeContext(error=_limited(503))
    budgeted = _budgeted(context, clock)

    for _ in range(STRIKES):
        with pytest.raises(requests.exceptions.HTTPError):
            budgeted.make_request("teams", "466.l.1")
    with pytest.raises(YahooUnavailableError):
        budgeted.make_request("teams", "466.l.1")

    assert len(context.requests) == STRIKES


def test_a_retry_after_pauses_every_request_for_as_long_as_it_asked() -> None:
    clock = Clock()
    context = FakeContext()
    context.fail_first = [_limited(999, "40")]
    budgeted = _budgeted(context, clock)

    with pytest.raises(requests.exceptions.HTTPError):
        budgeted.make_request("teams", "466.l.1")
    clock.now += 39
    with pytest.raises(YahooUnavailableError):
        budgeted.make_request("teams", "466.l.1")
    clock.now += 1

    assert budgeted.make_request("teams", "466.l.1") == "<fantasy_content/>"
    assert len(context.requests) == 2


def test_a_refused_session_stops_requests_reaching_yahoo() -> None:
    clock = Clock()
    context = FakeContext(error=YahooSessionExpiredError())
    budgeted = _budgeted(context, clock)

    for _ in range(2):
        with pytest.raises(YahooSessionExpiredError):
            budgeted.make_request("teams", "466.l.1")

    assert len(context.requests) == 1


def test_a_request_turned_down_for_good_counts_against_nothing() -> None:
    """A 404 is an answer about the request, not Yahoo pushing back."""
    clock = Clock()
    context = FakeContext(error=_limited(404))
    budgeted = _budgeted(context, clock)

    for _ in range(STRIKES + 1):
        with pytest.raises(requests.exceptions.HTTPError):
            budgeted.make_request("teams", "466.l.1")

    assert len(context.requests) == STRIKES + 1
