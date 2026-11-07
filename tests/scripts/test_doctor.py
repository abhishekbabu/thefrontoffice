"""Tests for the environment doctor.

Its reason to exist is that `AppSettings` ignores unrecognized keys, so a
mistyped one produces no error anywhere — the setting silently keeps its
default and the feature reports itself unavailable much later.
"""

from pathlib import Path
from typing import Any

import doctor
import pytest

from thefrontoffice.bootstrap import REGISTRY
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import AppSettings


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Where `.env` is read from: a file of the test's own, absent until written."""
    return tmp_path / ".env"


def _report(path: Path, **config: Any) -> int:
    """The doctor's verdict on `path`, with settings of the test's own."""
    env = EnvFile(path, settings=AppSettings(_env_file=None, **config))
    return doctor.main(env=env, registry=REGISTRY, providers=[])


# ── typo detection ──────────────────────────────────────────────────────


def test_a_mistyped_key_is_reported_and_fails(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path.write_text("GOOGLE_APIKEY=abc\n", encoding="utf-8")

    assert _report(path) == 1
    assert "GOOGLE_APIKEY" in capsys.readouterr().out


def test_a_correct_file_passes(path: Path) -> None:
    path.write_text("# GOOGLE_APIKEY=abc\n\nGOOGLE_API_KEY=abc\nSLEEPER_USERNAME=someone\n", encoding="utf-8")

    assert _report(path) == 0


def test_a_missing_env_file_is_reported_rather_than_crashing(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _report(path) == 0
    assert ".env.template" in capsys.readouterr().out  # names the file to start from


def test_every_competition_is_listed_with_what_it_needs(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _report(path)

    assert "SLEEPER_USERNAME" in capsys.readouterr().out


# ── never echoing a secret ──────────────────────────────────────────────


def _line(out: str, key: str) -> str:
    return next(line for line in out.splitlines() if line.strip().startswith(key))


def test_a_secret_is_reported_as_set_never_by_value(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _report(path, groq_api_key="super-secret-value")

    out = capsys.readouterr().out
    assert "super-secret-value" not in out
    assert _line(out, "GROQ_API_KEY").endswith("set")


def test_an_identifier_is_shown_because_it_is_not_a_secret(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reporting `set` for a username helps nobody verify anything."""
    _report(path, sleeper_username="abhibeast")

    assert _line(capsys.readouterr().out, "SLEEPER_USERNAME").endswith("abhibeast")


def test_an_unset_value_says_so(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _report(path)

    assert _line(capsys.readouterr().out, "GROQ_API_KEY").endswith("not set")


def test_a_boolean_is_not_rendered_as_python(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _report(path, logfire_capture_prompts=True)

    assert _line(capsys.readouterr().out, "LOGFIRE_CAPTURE_PROMPTS").endswith("true")


def test_prompt_capture_being_on_is_called_out(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """It sends the roster and the leagues, so it should never be a quiet default."""
    _report(path, logfire_capture_prompts=False)
    quiet = capsys.readouterr().out.splitlines()

    _report(path, logfire_capture_prompts=True)
    loud = capsys.readouterr().out.splitlines()

    assert len(loud) == len(quiet) + 1  # a line of its own, beyond what is shown when it is off
