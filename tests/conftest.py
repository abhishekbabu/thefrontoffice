"""Fixtures every test gets: the suite never reads this machine's configuration or caches.

Stand-ins and builders a test imports live in `support/`; fixtures only one
directory's tests need live in that directory's own `conftest.py`.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Blank every credential-derived setting for the duration of a test.

    `settings` is built from the developer's .env at import time. Without this a
    test asserting "unconfigured" behavior passes in CI, which has no .env, and
    fails on a machine that does — or worse, a test quietly exercises a real
    account. Tests that need a value set it explicitly.
    """
    from thefrontoffice.config.settings import settings

    for field in (
        "sleeper_username",
        "fpl_entry_id",
        "gemini_api_key",
        "groq_api_key",
        "openrouter_api_key",
        "yahoo_client_id",
        "yahoo_client_secret",
        # Without this, running the suite on a machine with a token in .env
        # exports spans from the tests into the developer's real project.
        "logfire_token",
    ):
        monkeypatch.setattr(settings, field, None)

    # Point the Yahoo token at a path that cannot exist, so a suite run does not
    # depend on whether this machine has been through the OAuth flow. A test
    # that wants an authorized client says so by pointing this somewhere real.
    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "no-token"))

    # Every disk cache lands under tmp_path too. The suite must not read a cache
    # this machine happens to have warmed, nor leave one behind that the next
    # run reads as a hit.
    for field, name in (
        ("yahoo_cache_dir", "yahoo-cache"),
        ("sleeper_cache_dir", "sleeper-cache"),
        ("fpl_cache_dir", "fpl-cache"),
        ("espn_cache_dir", "espn-cache"),
        ("answer_cache_dir", "answer-cache"),
        ("item_state_dir", "item-state"),
    ):
        monkeypatch.setattr(settings, field, str(tmp_path / name))
