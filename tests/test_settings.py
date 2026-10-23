"""Tests for env-var validation in AppSettings."""

from functools import partial

import pytest
from pydantic import ValidationError

from thefrontoffice.config.settings import AppSettings

# Settings from explicit values, ignoring any real .env on disk. A partial
# rather than a typed wrapper: several tests pass deliberately wrong values to
# see them refused, which a fully typed signature would reject before they ran.
_settings = partial(AppSettings, _env_file=None)


def test_defaults_match_the_documented_values() -> None:
    s = _settings()
    assert s.yahoo_max_weekly_adds == 3
    assert s.log_level == "INFO"
    assert s.yahoo_redirect_uri == "https://localhost:8080"


def test_non_numeric_add_limit_fails_loudly() -> None:
    """A malformed value must name the field it came from."""
    with pytest.raises(ValidationError, match="yahoo_max_weekly_adds"):
        _settings(yahoo_max_weekly_adds="three")


def test_negative_add_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(yahoo_max_weekly_adds=-1)


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        _settings(log_level="CHATTY")


def test_log_level_is_case_insensitive() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_missing_credentials_are_none_not_crashes() -> None:
    """--mock must work with no credentials at all."""
    s = _settings()
    assert s.gemini_api_key is None
    assert s.yahoo_client_id is None


def test_a_negative_add_budget_is_refused() -> None:
    assert _settings(yahoo_max_weekly_adds=0).yahoo_max_weekly_adds == 0
    with pytest.raises(ValidationError):
        _settings(yahoo_max_weekly_adds=-1)
