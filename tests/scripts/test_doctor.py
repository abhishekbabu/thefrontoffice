"""Tests for the environment doctor.

Its reason to exist is that `AppSettings` ignores unrecognized keys, so a
mistyped one produces no error anywhere — the setting silently keeps its
default and the feature reports itself unavailable much later.
"""

from pathlib import Path

import doctor
import pytest

from thefrontoffice.config import env_file
from thefrontoffice.config.settings import settings


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where `.env` is read from: a file of the test's own, absent until written."""
    path = tmp_path / ".env"
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    return path


# ── typo detection ──────────────────────────────────────────────────────


def test_a_mistyped_key_is_reported_and_fails(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env.write_text("GOOGLE_APIKEY=abc\n", encoding="utf-8")

    assert doctor.main() == 1
    assert "GOOGLE_APIKEY" in capsys.readouterr().out


def test_a_correct_file_passes(env: Path) -> None:
    env.write_text("# GOOGLE_APIKEY=abc\n\nGOOGLE_API_KEY=abc\nSLEEPER_USERNAME=someone\n", encoding="utf-8")

    assert doctor.main() == 0


def test_a_missing_env_file_is_reported_rather_than_crashing(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert doctor.main() == 0
    assert ".env.template" in capsys.readouterr().out  # names the file to start from


def test_every_competition_is_listed_with_what_it_needs(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doctor.main()

    assert "SLEEPER_USERNAME" in capsys.readouterr().out


# ── never echoing a secret ──────────────────────────────────────────────


def test_a_secret_is_reported_by_length_not_by_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "super-secret-value")

    assert doctor.describe("gemini_api_key") == "set (18 chars)"


def test_an_identifier_is_shown_because_it_is_not_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting `set (9 chars)` for a username helps nobody verify anything."""
    monkeypatch.setattr(settings, "sleeper_username", "abhibeast")

    assert doctor.describe("sleeper_username") == "abhibeast"


def test_an_unset_value_says_so() -> None:
    assert doctor.describe("gemini_api_key") == "not set"


def test_a_boolean_is_not_rendered_as_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "logfire_capture_prompts", True)

    assert doctor.describe("logfire_capture_prompts") == "true"


def test_prompt_capture_being_on_is_called_out(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It sends the roster and the leagues, so it should never be a quiet default."""
    monkeypatch.setattr(settings, "logfire_capture_prompts", False)
    doctor.main()
    quiet = capsys.readouterr().out.splitlines()

    monkeypatch.setattr(settings, "logfire_capture_prompts", True)
    doctor.main()
    loud = capsys.readouterr().out.splitlines()

    assert len(loud) == len(quiet) + 1  # a line of its own, beyond what is shown when it is off
