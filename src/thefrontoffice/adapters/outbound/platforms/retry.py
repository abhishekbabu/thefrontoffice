"""When a platform request is worth a second attempt, and when its failure means the platform is down.

Every platform this app talks to fails the same ways — the connection stalls,
the server answers 5xx, or it answers 429 to say "come back later" — so one
classification serves them all, and the outage a user is told about is read off
the same rules that decide a retry.

The distinction that matters is transient versus permanent: retrying a 404 or a
changed payload shape burns a rate-limit budget on a request that will fail
identically.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests
from tenacity import (
    RetryCallState,
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RATE_LIMITED = 429
"""How Sleeper, FPL, ESPN and Yahoo's API all say "too many requests"."""

DENIED = 999
"""How Yahoo's frontend hosts say it instead: a status outside HTTP's range, which `requests` will not raise on."""


def is_transient(exc: BaseException) -> bool:
    """Whether a failure is worth a second attempt."""
    return bool(outage(exc))


def outage(exc: BaseException) -> str:
    """What says the platform itself is not answering, in a few words; empty for any other failure.

    A 5xx is the server saying it cannot answer, a 429 or Yahoo's 999 it
    refusing to for now, and a timeout or a dropped connection it not answering
    at all. Any other 4xx is a request it understood and turned down, which
    waiting will not change.
    """
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return f"it answered {status}" if status >= 500 or status in (RATE_LIMITED, DENIED) else ""
    if isinstance(exc, requests.exceptions.Timeout):
        return "it timed out"
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return "the connection failed"
    return ""


def retry_after(exc: BaseException | None, now: datetime | None = None) -> float | None:
    """How many seconds a refusal asked to be left alone, from its `Retry-After`; None where it named none.

    The header is either a number of seconds or an HTTP date. A date already
    past asks for nothing, and an unreadable header is read as absent.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = str(headers.get("Retry-After", "")).strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to try a transient failure, backing off exponentially between attempts.

    Handed to each client by the composition root, so a test hands it one that
    keeps the attempts and drops the waiting.
    """

    attempts: int = 3
    min_wait: float = 2
    max_wait: float = 20
    multiplier: float = 2
    sleep: Callable[[float], None] = field(default=time.sleep, compare=False, repr=False)
    """How a wait is sat out: a test keeps the seconds it was asked for instead."""

    def worth_retrying(self, exc: BaseException) -> bool:
        """Whether `exc` is transient and asked for no longer a wait than this policy would ever sit out.

        A server naming a `Retry-After` past `max_wait` is not retried at all:
        asking again sooner than it said is the hammering the header is there
        to stop, and the caller hears of the refusal at once instead.
        """
        wait = retry_after(exc)
        return is_transient(exc) and (wait is None or wait <= self.max_wait)

    def _wait(self, state: RetryCallState) -> float:
        """The backoff, or the `Retry-After` the refusal named where that is longer."""
        backoff = wait_exponential(multiplier=self.multiplier, min=self.min_wait, max=self.max_wait)(state)
        asked = retry_after(state.outcome.exception()) if state.outcome is not None else None
        return max(backoff, asked or 0.0)

    def call[T](self, fetch: Callable[[], T]) -> T:
        """`fetch`, retried while it fails transiently, waiting at least as long as a `Retry-After` asks.

        The original error is re-raised once attempts run out, so the caller can
        translate it into its own platform's error. Tenacity's state lives in
        the `Retrying` built here, one per call.
        """
        retrying = Retrying(
            stop=stop_after_attempt(self.attempts),
            wait=self._wait,
            retry=retry_if_exception(self.worth_retrying),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            sleep=self.sleep,
            reraise=True,
        )
        return retrying(fetch)
