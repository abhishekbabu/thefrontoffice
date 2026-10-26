"""Tests for the environment doctor.

Its reason to exist is that `AppSettings` ignores unrecognized keys, so a
mistyped one produces no error anywhere — the setting silently keeps its
default and the feature reports itself unavailable much later.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import doctor  # noqa: E402


def _env(tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(doctor, "ENV_FILE", path)
    return path


# ── the declared surface ────────────────────────────────────────────────


def _declared_names() -> list[str]:
    return list(doctor._declared().values())


def test_an_aliased_field_reports_the_variable_that_is_actually_read() -> None:
    """`gemini_api_key` reads GOOGLE_API_KEY, and that is what a user types."""
    assert doctor._declared()["GOOGLE_API_KEY"] == "gemini_api_key"


def test_a_plain_field_maps_to_its_uppercase_name() -> None:
    assert doctor._declared()["SLEEPER_USERNAME"] == "sleeper_username"


# ── typo detection ──────────────────────────────────────────────────────


def test_a_mistyped_key_is_reported_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(tmp_path, "GOOGLE_APIKEY=abc\n", monkeypatch)

    assert doctor.main() == 1
    assert "GOOGLE_APIKEY" in capsys.readouterr().out


def test_a_correct_file_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(tmp_path, "GOOGLE_API_KEY=abc\nSLEEPER_USERNAME=someone\n", monkeypatch)

    assert doctor.main() == 0
    assert "Unrecognized" not in capsys.readouterr().out


def test_comments_and_blank_lines_are_not_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(tmp_path, "# GOOGLE_APIKEY=abc\n\n   \nGOOGLE_API_KEY=abc\n", monkeypatch)
    assert doctor._file_keys() == ["GOOGLE_API_KEY"]


def test_a_missing_env_file_is_reported_rather_than_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor, "ENV_FILE", tmp_path / "absent")

    assert doctor.main() == 0
    assert "MISSING" in capsys.readouterr().out


# ── never echoing a secret ──────────────────────────────────────────────


def test_a_secret_is_reported_by_length_not_by_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.settings, "gemini_api_key", "super-secret-value")

    described = doctor._describe("gemini_api_key")
    assert "super-secret-value" not in described
    assert described == "set (18 chars)"


def test_an_identifier_is_shown_because_it_is_not_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting `set (9 chars)` for a username helps nobody verify anything."""
    monkeypatch.setattr(doctor.settings, "sleeper_username", "abhibeast")
    assert doctor._describe("sleeper_username") == "abhibeast"


def test_an_unset_value_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.settings, "gemini_api_key", None)
    assert doctor._describe("gemini_api_key") == "not set"


def test_a_boolean_is_not_rendered_as_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.settings, "logfire_capture_prompts", True)
    assert doctor._describe("logfire_capture_prompts") == "true"


def test_prompt_capture_being_on_is_called_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It sends the roster and the leagues, so it should never be a quiet default."""
    _env(tmp_path, "", monkeypatch)
    monkeypatch.setattr(doctor.settings, "logfire_capture_prompts", True)

    doctor.main()
    assert "prompt text IS being exported" in capsys.readouterr().out
