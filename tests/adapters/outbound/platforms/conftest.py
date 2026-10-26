"""Fixtures for the platform clients' tests."""

import importlib

import pytest

CLIENTS = ("sleeper", "fpl", "espn")
"""The public-API clients, each retrying through its own `_retry` policy."""


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every client's retries, with no backoff between them: the backoff is real seconds otherwise.

    The policy is kept — the attempts, what counts as transient — so a test
    still sees each retry happen; only the waiting goes.
    """
    for name in CLIENTS:
        module = importlib.import_module(f"thefrontoffice.adapters.outbound.platforms.{name}.client")
        original = module._retry
        monkeypatch.setattr(module, "_retry", lambda original=original: original().copy(wait=lambda _: 0))
