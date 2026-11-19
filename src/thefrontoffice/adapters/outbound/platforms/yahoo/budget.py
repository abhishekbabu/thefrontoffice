"""How hard this app may lean on Yahoo: a pace, a cap on concurrent requests, and a stop when Yahoo pushes back.

Read with the person's own session cookie, every request is theirs: Yahoo sees
one signed-in browser asking for hundreds of pages in seconds, and a host that
throttles or flags that account costs them more than a slow page. So each host
gets one budget for the whole process, shared by every request handler that
builds a reader — a token bucket for the sustained rate, a semaphore for how
many may be in flight, and a breaker that stops asking for a while once Yahoo
refuses repeatedly or says when to come back.

Two more savings sit beside it. Concurrent asks for the same path share one
request (`SingleFlight`), as two panels of one page often ask for the same
scoreboard. And a copy just past its freshness is served at once while one
background thread refreshes it (`Refresher`), so a page never waits on Yahoo
for something it read a moment ago.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.retry import outage, retry_after
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooContext
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooSessionExpiredError, YahooUnavailableError
from thefrontoffice.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)

RATE = 2.0
"""Requests a second, sustained: a person paging through Yahoo's own site asks about as often."""

BURST = 4
"""How many may go at once after a quiet spell, before the rate applies."""

CONCURRENCY = 2
"""Requests in flight at any moment, however many threads want one."""

STRIKES = 3
"""Consecutive refusals or outages before the breaker opens: one read's every attempt."""

COOLDOWN = 120.0
"""Seconds the breaker stays open, where Yahoo named no `Retry-After` of its own."""

REFUSED_COOLDOWN = 600.0
"""Seconds to stop asking once Yahoo refused the session: no request will succeed until the cookie changes."""

REFRESH_QUEUE = 64
"""Background refreshes waiting at most; past it a stale copy simply waits for the next page to ask."""


class Throttle:
    """A token bucket and a concurrency cap: at most `rate` a second after a `burst`, `concurrency` at once.

    A caller over the rate reserves its slot and sleeps until it comes due,
    outside the lock, so waiting callers queue in arrival order without
    holding each other up.
    """

    def __init__(
        self,
        rate: float = RATE,
        burst: int = BURST,
        concurrency: int = CONCURRENCY,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = rate
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()
        self._in_flight = threading.BoundedSemaphore(concurrency)

    def _reserve(self) -> float:
        """Take a token, borrowing against the refill where none is left; how long until it is ours."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
            self._last = now
            self._tokens -= 1
            return 0.0 if self._tokens >= 0 else -self._tokens / self._rate

    @contextmanager
    def slot(self) -> Generator[None]:
        """Hold one of the in-flight places, once the rate allows another request."""
        with self._in_flight:
            wait = self._reserve()
            if wait > 0:
                self._sleep(wait)
            yield


class Breaker:
    """Stops asking a host that keeps refusing, for a while.

    Closed, every request goes. `STRIKES` consecutive failures open it for
    `COOLDOWN`; a `Retry-After` opens it at once for exactly as long as Yahoo
    asked; a refused session opens it at once too, since nothing will succeed
    until the cookie changes. Once the pause is over requests resume, but the
    count stands until one succeeds: the first failure opens it again.
    """

    def __init__(
        self, strikes: int = STRIKES, cooldown: float = COOLDOWN, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._strikes = strikes
        self._cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._until = 0.0
        self._why: Callable[[], FrontOfficeError] = lambda: YahooUnavailableError("it kept refusing")
        self._lock = threading.Lock()

    def check(self) -> None:
        """Let a request through, unless the breaker is open.

        Raises:
            YahooSessionExpiredError: Yahoo refused the session, moments ago.
            YahooUnavailableError: Yahoo kept refusing or failing, and the pause is not over.
        """
        with self._lock:
            if self._clock() < self._until:
                raise self._why()

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0

    def failed(self, pause: float | None = None) -> None:
        """Count a refusal or an outage; `pause` is what Yahoo asked for, which opens the breaker outright."""
        with self._lock:
            self._failures += 1
            if pause is None and self._failures < self._strikes:
                return
            seconds = self._cooldown if pause is None else pause
            self._open(seconds, lambda: YahooUnavailableError(f"it kept refusing; trying again in {seconds:.0f}s"))

    def refused(self, pause: float = REFUSED_COOLDOWN) -> None:
        """Yahoo turned the session away: stop asking with it until the pause is over."""
        with self._lock:
            self._failures = self._strikes
            self._open(pause, YahooSessionExpiredError)

    def _open(self, seconds: float, why: Callable[[], FrontOfficeError]) -> None:
        self._until = self._clock() + seconds
        self._why = why
        logger.warning(f"Pausing requests to Yahoo for {seconds:.0f}s")


class SingleFlight:
    """Concurrent asks for the same key share one call: the first runs it, the rest wait for its answer."""

    def __init__(self) -> None:
        self._flights: dict[Any, Future[Any]] = {}
        self._lock = threading.Lock()

    def share[T](self, key: Any, call: Callable[[], T]) -> T:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = Future()
        if not leader:
            return flight.result()
        try:
            value = call()
        except BaseException as e:
            flight.set_exception(e)
            raise
        else:
            flight.set_result(value)
            return value
        finally:
            with self._lock:
                del self._flights[key]


class Refresher:
    """Refreshes stale copies on one background thread, a key at most once at a time and a bounded few queued.

    Each refresh stores what it fetched in a cache it opens itself, on its own
    thread, since a cache holds what it has read in memory and is written from
    one thread only. A refresh that fails leaves the stale copy standing: the
    next read past its limit fetches in the foreground and says why.
    """

    def __init__(self, cache: Callable[[], DiskCache], *, limit: int = REFRESH_QUEUE) -> None:
        self._cache = cache
        self._jobs: queue.Queue[tuple[str, Callable[[], Any]]] = queue.Queue(maxsize=limit)
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def refresh(self, key: str, fetch: Callable[[], Any]) -> None:
        """Fetch `key` again in the background and store it; nothing where it is already queued or the queue is full."""
        with self._lock:
            if key in self._pending:
                return
            try:
                self._jobs.put_nowait((key, fetch))
            except queue.Full:
                logger.debug(f"Refresh queue full; {key} waits for the next read")
                return
            self._pending.add(key)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="yahoo-refresh", daemon=True)
                self._worker.start()

    def settle(self) -> None:
        """Wait until every queued refresh has finished: for a caller that must see their results."""
        self._jobs.join()

    def _run(self) -> None:
        while True:
            key, fetch = self._jobs.get()
            try:
                self._cache().set(key, fetch())
            except FrontOfficeError as e:
                logger.warning(f"Background refresh of {key} failed; the stale copy stands: {e}")
            except Exception:
                logger.exception(f"Background refresh of {key} failed unexpectedly")
            finally:
                with self._lock:
                    self._pending.discard(key)
                self._jobs.task_done()


@dataclass
class Budget:
    """Everything one Yahoo host shares across the process: built once by bootstrap, handed to each reader."""

    throttle: Throttle = field(default_factory=Throttle)
    breaker: Breaker = field(default_factory=Breaker)
    flights: SingleFlight = field(default_factory=SingleFlight)


class BudgetedContext:
    """A `YahooContext` that asks Yahoo within a `Budget`: paced, capped, shared and stopped when refused."""

    def __init__(self, context: YahooContext, budget: Budget) -> None:
        self._context = context
        self._budget = budget

    def make_request(self, url: str, league: str | bool = False) -> str:
        """The raw XML for `url`, as the wrapped context answers it — or the reason the breaker is open.

        Raises:
            YahooSessionExpiredError: Yahoo refused the session, now or moments ago.
            YahooUnavailableError: the breaker is open after repeated refusals.
            requests.HTTPError: anything else the wrapped context raised, for `call` to retry or translate.
        """
        return self._budget.flights.share((url, league), lambda: self._ask(url, league))

    def _ask(self, url: str, league: str | bool) -> str:
        breaker = self._budget.breaker
        breaker.check()
        with self._budget.throttle.slot():
            breaker.check()  # it may have opened while this waited its turn
            try:
                raw = self._context.make_request(url, league)
            except YahooSessionExpiredError:
                breaker.refused()
                raise
            except Exception as e:
                if outage(e):
                    breaker.failed(retry_after(e))
                raise
        breaker.succeeded()
        return raw
