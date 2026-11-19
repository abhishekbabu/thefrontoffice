"""Tests for the retry policy and outage classification shared by the platform clients."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
import requests
from support.http import NO_WAIT, http_error

from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy, is_transient, outage, retry_after

# ── classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        http_error(503),
        http_error(429),
        http_error(999),
        requests.exceptions.Timeout(),
        requests.exceptions.ConnectionError(),
        requests.exceptions.ChunkedEncodingError(),
    ],
    ids=["server-error", "rate-limited", "yahoo-denied", "timeout", "refused", "dropped-mid-response"],
)
def test_every_transient_failure_is_an_outage(error: Exception) -> None:
    """One classification: what is worth retrying is what, once retries run out, says to wait.

    Yahoo's frontend hosts answer 999 where an API would answer 429.
    """
    assert is_transient(error)
    assert outage(error)


@pytest.mark.parametrize("status", [503, 429, 999])
def test_an_outage_answered_with_a_status_names_it(status: int) -> None:
    assert str(status) in outage(http_error(status))


@pytest.mark.parametrize(
    "error",
    [http_error(400), http_error(404), requests.exceptions.HTTPError(), KeyError("leagueSchedule"), ValueError("x")],
    ids=["400", "404", "no-response", "changed-shape", "bad-literal"],
)
def test_a_permanent_failure_is_neither_retried_nor_an_outage(error: Exception) -> None:
    """Retrying a 404 or a changed payload burns the budget on a request that will fail identically."""
    assert not is_transient(error)
    assert outage(error) == ""


# ── behavior ───────────────────────────────────────────────────────────


def test_a_transient_failure_then_success_is_retried() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise requests.exceptions.Timeout()
        return "ok"

    assert NO_WAIT.call(flaky) == "ok"
    assert len(calls) == 2


def test_a_permanent_failure_is_not_retried() -> None:
    calls: list[int] = []

    def broken() -> str:
        calls.append(1)
        raise http_error(404)

    with pytest.raises(requests.exceptions.HTTPError):
        NO_WAIT.call(broken)
    assert len(calls) == 1


def test_attempts_are_bounded_and_the_original_error_reraises() -> None:
    """Callers translate the original error into a domain error."""
    calls: list[int] = []

    def always() -> str:
        calls.append(1)
        raise requests.exceptions.Timeout()

    with pytest.raises(requests.exceptions.Timeout):
        NO_WAIT.call(always)
    assert len(calls) == NO_WAIT.attempts


def _asked_to_wait(status: int, after: str) -> requests.exceptions.HTTPError:
    error = http_error(status)
    assert error.response is not None
    error.response.headers["Retry-After"] = after
    return error


# ── Retry-After ────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("after", "seconds"),
    [
        ("30", 30.0),
        (format_datetime(NOW + timedelta(seconds=90), usegmt=True), 90.0),
        (format_datetime(NOW - timedelta(seconds=90), usegmt=True), 0.0),
        ("Wed, 19 Nov 2026 12:01:30", 90.0),
        ("soon", None),
        ("", None),
    ],
    ids=["seconds", "date", "date-past", "date-without-zone", "unreadable", "blank"],
)
def test_a_retry_after_is_read_as_seconds_or_a_date(after: str, seconds: float | None) -> None:
    assert retry_after(_asked_to_wait(429, after), now=NOW) == seconds


def test_a_failure_naming_no_wait_asks_for_none() -> None:
    assert retry_after(http_error(503)) is None
    assert retry_after(requests.exceptions.Timeout()) is None


def test_a_retry_waits_at_least_as_long_as_the_server_asked() -> None:
    slept: list[float] = []
    policy = RetryPolicy(min_wait=1, max_wait=60, sleep=slept.append)
    failures = [_asked_to_wait(429, "45")]

    def limited() -> str:
        if failures:
            raise failures.pop()
        return "ok"

    assert policy.call(limited) == "ok"
    assert slept == [45.0]


def test_a_server_asking_for_longer_than_the_policy_would_wait_is_not_asked_again() -> None:
    """Retrying sooner than it said is the hammering the header exists to stop."""
    calls: list[int] = []
    policy = RetryPolicy(min_wait=1, max_wait=20, sleep=lambda _: None)

    def limited() -> str:
        calls.append(1)
        raise _asked_to_wait(999, "120")

    with pytest.raises(requests.exceptions.HTTPError):
        policy.call(limited)
    assert len(calls) == 1
