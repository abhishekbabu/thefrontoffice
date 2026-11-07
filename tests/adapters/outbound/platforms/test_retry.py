"""Tests for the retry policy and outage classification shared by the platform clients."""

import pytest
import requests
from support.http import NO_WAIT, http_error

from thefrontoffice.adapters.outbound.platforms.retry import is_transient, outage

# ── classification ──────────────────────────────────────────────────────


def test_network_failures_are_transient() -> None:
    """A stalled connection is how most rate limiting presents."""
    assert is_transient(requests.exceptions.Timeout())
    assert is_transient(requests.exceptions.ConnectTimeout())
    assert is_transient(requests.exceptions.ReadTimeout())
    assert is_transient(requests.exceptions.ConnectionError())
    assert is_transient(requests.exceptions.ChunkedEncodingError())


def test_server_errors_are_transient() -> None:
    assert is_transient(http_error(500))
    assert is_transient(http_error(503))


def test_client_errors_are_not() -> None:
    """Retrying a 404 burns the budget on a request that will fail identically."""
    assert not is_transient(http_error(400))
    assert not is_transient(http_error(404))


def test_rate_limiting_is_transient() -> None:
    """Every platform here says "come back later" with a 429."""
    assert is_transient(http_error(429))


def test_an_http_error_without_a_response_is_not_transient() -> None:
    assert not is_transient(requests.exceptions.HTTPError())


def test_unrelated_exceptions_are_not_transient() -> None:
    """A changed payload shape will not fix itself."""
    assert not is_transient(KeyError("leagueSchedule"))
    assert not is_transient(ValueError("bad literal"))


# ── what an outage is ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (http_error(503), "it answered 503"),
        (http_error(429), "it answered 429"),
        (requests.exceptions.Timeout(), "it timed out"),
        (requests.exceptions.ConnectionError(), "the connection failed"),
        (requests.exceptions.ChunkedEncodingError(), "the connection failed"),
    ],
    ids=["server-error", "rate-limited", "timeout", "refused", "dropped-mid-response"],
)
def test_every_transient_failure_is_an_outage_named_in_a_few_words(error: Exception, said: str) -> None:
    """One classification: what is worth retrying is what, once retries run out, says to wait."""
    assert outage(error) == said


@pytest.mark.parametrize("error", [http_error(404), requests.exceptions.HTTPError(), ValueError("bad json")])
def test_a_permanent_failure_is_no_outage(error: Exception) -> None:
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
