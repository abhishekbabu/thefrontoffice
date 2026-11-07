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
from collections.abc import Callable
from dataclasses import dataclass

import requests
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RATE_LIMITED = 429
"""How Sleeper, FPL, ESPN and Yahoo all say "too many requests"."""


def is_transient(exc: BaseException) -> bool:
    """Whether a failure is worth a second attempt."""
    return bool(outage(exc))


def outage(exc: BaseException) -> str:
    """What says the platform itself is not answering, in a few words; empty for any other failure.

    A 5xx is the server saying it cannot answer, a 429 it refusing to for now,
    and a timeout or a dropped connection it not answering at all. Any other 4xx
    is a request it understood and turned down, which waiting will not change.
    """
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return f"it answered {status}" if status >= 500 or status == RATE_LIMITED else ""
    if isinstance(exc, requests.exceptions.Timeout):
        return "it timed out"
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return "the connection failed"
    return ""


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

    def call[T](self, fetch: Callable[[], T]) -> T:
        """`fetch`, retried while it fails transiently.

        The original error is re-raised once attempts run out, so the caller can
        translate it into its own platform's error. Tenacity's state lives in
        the `Retrying` built here, one per call.
        """
        retrying = Retrying(
            stop=stop_after_attempt(self.attempts),
            wait=wait_exponential(multiplier=self.multiplier, min=self.min_wait, max=self.max_wait),
            retry=retry_if_exception(is_transient),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        return retrying(fetch)
