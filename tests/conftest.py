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

    A test of the registry, the wiring or an inbound adapter hands it settings
    of its own and needs none of this. What is left reads the process's
    settings because it is called once per process with nothing to hand it —
    `setup_logging`, the telemetry, an entry point's `main` — and those are
    built from the developer's .env at import time. Without this, a test of
    them passes in CI, which has no .env, and fails on a machine that does, or
    exports spans to a real project. Every field is reset, so a new one needs
    no entry here.
    """
    isolated = isolated_settings(tmp_path)
    for field in AppSettings.model_fields:
        monkeypatch.setattr(settings, field, getattr(isolated, field))
