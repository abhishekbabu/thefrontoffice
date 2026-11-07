"""Fixtures every test gets: the suite never reads this machine's configuration or caches.

Stand-ins and builders a test imports live in `support/`; fixtures only one
directory's tests need live in that directory's own `conftest.py`.
"""

from pathlib import Path

import pytest
from support.settings import isolated_settings

from thefrontoffice.config.settings import AppSettings, settings


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The process's settings, as `isolated_settings` builds them, for the duration of a test.

    Code handed no settings of its own — an entry point, telemetry — reads the
    process's, which are built from the developer's .env at import time. Without
    this a test asserting "unconfigured" behavior passes in CI, which has no
    .env, and fails on a machine that does; a test quietly exercises a real
    account, exports spans to a real project, or reads a cache this machine
    warmed. Every field is reset, so a new one needs no entry here.
    """
    isolated = isolated_settings(tmp_path)
    for field in AppSettings.model_fields:
        monkeypatch.setattr(settings, field, getattr(isolated, field))
