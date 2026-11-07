"""Tests for tracing configuration.

The properties that matter are negative ones: without a token nothing leaves
the machine, and prompt text is not exported unless it is asked for.
"""

from typing import Any

import pytest

from thefrontoffice.config import telemetry
from thefrontoffice.config.settings import AppSettings


def _telemetry(**config: Any) -> telemetry.Telemetry:
    """A process's tracing, not yet set up, over settings of the test's own."""
    return telemetry.Telemetry(AppSettings(_env_file=None, **config))


class FakeLogfire:
    """Records what the real logfire would have been asked to do."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.instrumented: list[str] = []

    def configure(self, **kwargs: Any) -> None:
        self.config = kwargs

    def instrument_requests(self) -> None:
        self.instrumented.append("requests")

    def instrument_google_genai(self) -> None:
        self.instrumented.append("google_genai")

    def instrument_pydantic(self) -> None:
        self.instrumented.append("pydantic")

    def instrument_openai(self) -> None:
        self.instrumented.append("openai")

    def LogfireLoggingHandler(self) -> Any:  # noqa: N802 — mirrors the real class name
        import logging

        return logging.NullHandler()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeLogfire:
    stub = FakeLogfire()
    monkeypatch.setitem(__import__("sys").modules, "logfire", stub)
    # Set, then removed: monkeypatch records a variable only once it has touched
    # it, and `setup_telemetry` writes os.environ itself — so an absent variable
    # it sets would otherwise outlive the test.
    monkeypatch.setenv(telemetry.CAPTURE_CONTENT_VAR, "")
    monkeypatch.delenv(telemetry.CAPTURE_CONTENT_VAR)
    return stub


# ── exporting nothing by default ────────────────────────────────────────


def test_without_a_token_nothing_is_exported(fake: FakeLogfire) -> None:
    """A fresh clone and CI must make no network call because logfire is installed."""
    _telemetry().setup("front-office-cli")
    assert fake.config["send_to_logfire"] == "if-token-present"
    assert fake.config["token"] is None


def test_a_token_is_passed_through(fake: FakeLogfire) -> None:
    _telemetry(logfire_token="pylf_v1_test").setup("front-office-cli")
    assert fake.config["token"] == "pylf_v1_test"


def test_prompt_text_is_not_exported_by_default(fake: FakeLogfire) -> None:
    """Prompts carry the roster, the leagues and the FPL entry id."""
    import os

    _telemetry().setup("front-office-cli")
    assert os.environ[telemetry.CAPTURE_CONTENT_VAR] == "false"


def test_prompt_capture_can_be_turned_on(fake: FakeLogfire) -> None:
    import os

    _telemetry(logfire_capture_prompts=True).setup("front-office-cli")
    assert os.environ[telemetry.CAPTURE_CONTENT_VAR] == "true"


def test_an_explicit_otel_variable_wins(fake: FakeLogfire, monkeypatch: pytest.MonkeyPatch) -> None:
    """So a single debugging run can capture prompts without editing .env."""
    import os

    monkeypatch.setenv(telemetry.CAPTURE_CONTENT_VAR, "true")
    _telemetry().setup("front-office-cli")
    assert os.environ[telemetry.CAPTURE_CONTENT_VAR] == "true"


# ── what gets instrumented ──────────────────────────────────────────────


def test_the_libraries_carrying_the_latency_are_instrumented(fake: FakeLogfire) -> None:
    """Every call this app waits on is an HTTP request or a Gemini call."""
    _telemetry().setup("front-office-cli")
    assert set(fake.instrumented) == {"requests", "google_genai", "pydantic"}


def test_the_front_end_names_itself(fake: FakeLogfire) -> None:
    _telemetry(logfire_environment="laptop").setup("front-office-web")
    assert fake.config["service_name"] == "front-office-web"
    assert fake.config["environment"] == "laptop"


def test_spans_do_not_go_to_the_console(fake: FakeLogfire) -> None:
    """The CLI prints a formatted UI to the same stream."""
    _telemetry().setup("front-office-cli")
    assert fake.config["console"] is False


def test_configuring_twice_instruments_once(fake: FakeLogfire) -> None:
    """Instrumenting a library twice would trace each call twice."""
    process = _telemetry()
    process.setup("front-office-web")
    process.setup("front-office-web")
    assert fake.instrumented == ["requests", "google_genai", "pydantic"]


def test_standard_library_logs_are_bridged(fake: FakeLogfire) -> None:
    """Retry warnings and cache-hit lines already go through logging."""
    import logging

    before = len(logging.getLogger().handlers)
    _telemetry().setup("front-office-cli")
    assert len(logging.getLogger().handlers) == before + 1
    logging.getLogger().handlers.pop()


def test_openai_calls_are_traced_only_where_prompt_text_may_leave(fake: FakeLogfire) -> None:
    """Its instrumentation records message text regardless, and a message carries the roster."""
    _telemetry().setup("api")
    assert "openai" not in fake.instrumented

    _telemetry(logfire_capture_prompts=True).setup("api")
    assert "openai" in fake.instrumented
