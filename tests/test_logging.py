"""Tests for logging setup: `config/logging.py`."""

import logging
from collections.abc import Iterator

import pytest

from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import settings


@pytest.fixture(autouse=True)
def _restore_root() -> Iterator[None]:
    """Put the root logger back as it was: what this sets up would otherwise outlive the test."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    root.setLevel(level)
    root.handlers[:] = handlers


def test_root_level_follows_the_configured_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "log_level", "DEBUG")

    setup_logging()

    assert logging.getLogger().level == logging.DEBUG


def test_repeated_calls_do_not_stack_handlers() -> None:
    """Every entry point calls this, and one process can run more than one."""
    setup_logging()
    before = len(logging.getLogger().handlers)
    setup_logging()
    assert len(logging.getLogger().handlers) == before


def test_noisy_third_party_loggers_are_quieted() -> None:
    """yahoofantasy and urllib3 at INFO would bury the report in request logs."""
    setup_logging()
    for name in ("yahoofantasy", "urllib3", "oauthlib", "requests_oauthlib"):
        assert logging.getLogger(name).level == logging.WARNING
