"""Tests for env-var validation in AppSettings."""

from functools import partial

import pytest
from pydantic import ValidationError

from thefrontoffice.config.settings import ADVANCED, AppSettings, env_var, group, is_secret

# Settings from explicit values, ignoring any real .env on disk. A partial
# rather than a typed wrapper: several tests pass deliberately wrong values to
# see them refused, which a fully typed signature would reject before they ran.
_settings = partial(AppSettings, _env_file=None)


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        _settings(log_level="CHATTY")


def test_log_level_is_case_insensitive() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_missing_credentials_are_none_not_crashes() -> None:
    """The app starts with nothing set; each feature names the credential it lacks."""
    s = _settings()
    assert s.gemini_api_key is None
    assert s.yahoo_client_id is None


def test_a_negative_add_budget_is_refused() -> None:
    assert _settings(yahoo_max_weekly_adds=0).yahoo_max_weekly_adds == 0
    with pytest.raises(ValidationError):
        _settings(yahoo_max_weekly_adds=-1)


def test_blank_is_absent_for_any_setting_that_may_be_absent() -> None:
    """`KEY=` is how people write "I do not use this"; an empty string would read as a key that is set."""
    s = _settings(sleeper_username=" ", fpl_entry_id="", logfire_token="")
    assert (s.sleeper_username, s.fpl_entry_id, s.logfire_token) == (None, None, None)


def test_an_aliased_field_reports_the_variable_a_user_types() -> None:
    assert env_var("gemini_api_key") == "GOOGLE_API_KEY"


def test_a_plain_field_maps_to_its_uppercase_name() -> None:
    assert env_var("sleeper_username") == "SLEEPER_USERNAME"


def test_credentials_are_secret_and_identifiers_are_not() -> None:
    """A username is shown so it can be checked; a key never is."""
    assert is_secret("gemini_api_key") and is_secret("yahoo_client_secret")
    assert not is_secret("sleeper_username") and not is_secret("fpl_entry_id")


def test_every_setting_says_what_it_unlocks() -> None:
    assert all(group(field) for field in AppSettings.model_fields)
    assert group("log_level") == ADVANCED
