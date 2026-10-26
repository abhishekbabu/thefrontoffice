"""Tests for the retry policy shared by the platform clients."""

from collections.abc import Callable

import pytest
import requests
from tenacity import Retrying

from thefrontoffice.adapters.outbound.platforms.retry import build_retry, is_transient


def _http(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


# ── classification ──────────────────────────────────────────────────────


def test_network_failures_are_transient() -> None:
    """A stalled connection is how most rate limiting presents."""
    assert is_transient(requests.exceptions.Timeout())
    assert is_transient(requests.exceptions.ConnectTimeout())
    assert is_transient(requests.exceptions.ReadTimeout())
    assert is_transient(requests.exceptions.ConnectionError())
    assert is_transient(requests.exceptions.ChunkedEncodingError())


def test_server_errors_are_transient() -> None:
    assert is_transient(_http(500))
    assert is_transient(_http(503))


def test_client_errors_are_not() -> None:
    """Retrying a 404 burns the budget on a request that will fail identically."""
    assert not is_transient(_http(400))
    assert not is_transient(_http(404))
    assert not is_transient(_http(429))


def test_a_platform_can_add_its_own_retryable_codes() -> None:
    assert is_transient(_http(429), frozenset({429}))
    assert not is_transient(_http(404), frozenset({429}))


def test_an_http_error_without_a_response_is_not_transient() -> None:
    assert not is_transient(requests.exceptions.HTTPError())


def test_unrelated_exceptions_are_not_transient() -> None:
    """A changed payload shape will not fix itself."""
    assert not is_transient(KeyError("leagueSchedule"))
    assert not is_transient(ValueError("bad literal"))


# ── behavior ───────────────────────────────────────────────────────────


def _retry(predicate: Callable[[BaseException], bool] = is_transient) -> Retrying:
    """A retry that does not really sleep, so the suite stays fast."""
    return build_retry(attempts=3, multiplier=1, min_wait=0, max_wait=0, predicate=predicate).copy(wait=lambda _: 0)


def test_a_transient_failure_then_success_is_retried() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise requests.exceptions.Timeout()
        return "ok"

    assert _retry()(flaky) == "ok"
    assert len(calls) == 2


def test_a_permanent_failure_is_not_retried() -> None:
    calls: list[int] = []

    def broken() -> str:
        calls.append(1)
        raise _http(404)

    with pytest.raises(requests.exceptions.HTTPError):
        _retry()(broken)
    assert len(calls) == 1


def test_attempts_are_bounded_and_the_original_error_reraises() -> None:
    """Callers translate the original error into a domain error."""
    calls: list[int] = []

    def always() -> str:
        calls.append(1)
        raise requests.exceptions.Timeout()

    with pytest.raises(requests.exceptions.Timeout):
        _retry()(always)
    assert len(calls) == 3
