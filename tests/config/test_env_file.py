"""Tests for editing `.env` in place.

This module writes the file that holds every credential, so the assertions are
mostly about what it must not do: invent keys, lose comments, or mangle a value
on the way back out.
"""

from pathlib import Path

import pytest

from thefrontoffice.config import env_file
from thefrontoffice.config.settings import settings

TEMPLATE = """# Yahoo credentials
YAHOO_CLIENT_ID=abc
YAHOO_CLIENT_SECRET=

# Sleeper — no key needed
SLEEPER_USERNAME=abhibeast
LOG_LEVEL=INFO
"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    path.write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    # Reloading would re-read the developer's real file, not this one.
    monkeypatch.setattr(env_file, "reload_settings", lambda: None)
    return path


# ── what the app declares ───────────────────────────────────────────────


def test_an_aliased_field_reports_the_variable_a_user_types() -> None:
    assert env_file.env_var("gemini_api_key") == "GOOGLE_API_KEY"


def test_a_plain_field_maps_to_its_uppercase_name() -> None:
    assert env_file.env_var("sleeper_username") == "SLEEPER_USERNAME"


# ── reading ─────────────────────────────────────────────────────────────


def test_values_are_read_in_file_order(env: Path) -> None:
    assert list(env_file.read_values()) == [
        "YAHOO_CLIENT_ID",
        "YAHOO_CLIENT_SECRET",
        "SLEEPER_USERNAME",
        "LOG_LEVEL",
    ]


def test_comments_are_not_keys(env: Path) -> None:
    assert "# Yahoo credentials" not in env_file.read_values()


def test_a_missing_file_reads_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_file, "ENV_PATH", tmp_path / "absent")
    assert env_file.read_values() == {}


def test_a_quoted_value_reads_back_unquoted(env: Path) -> None:
    env.write_text('SLEEPER_USERNAME="two words"\n', encoding="utf-8")
    assert env_file.read_values()["SLEEPER_USERNAME"] == "two words"


# ── writing ─────────────────────────────────────────────────────────────


def test_an_existing_key_is_replaced_in_place(env: Path) -> None:
    env_file.write_values({"SLEEPER_USERNAME": "someone-else"})
    assert env_file.read_values()["SLEEPER_USERNAME"] == "someone-else"


def test_comments_and_ordering_survive_a_write(env: Path) -> None:
    """The file is a person's, not this app's — regenerating it would lose that."""
    env_file.write_values({"SLEEPER_USERNAME": "someone-else"})
    text = env.read_text(encoding="utf-8")

    assert "# Yahoo credentials" in text
    assert "# Sleeper — no key needed" in text
    assert text.index("YAHOO_CLIENT_ID") < text.index("SLEEPER_USERNAME")


def test_a_new_key_is_appended(env: Path) -> None:
    env_file.write_values({"FPL_ENTRY_ID": "12345"})
    assert env_file.read_values()["FPL_ENTRY_ID"] == "12345"


def test_an_untouched_key_keeps_its_value(env: Path) -> None:
    env_file.write_values({"FPL_ENTRY_ID": "12345"})
    assert env_file.read_values()["YAHOO_CLIENT_ID"] == "abc"


def test_a_key_no_setting_reads_is_refused(env: Path) -> None:
    """A line nothing picks up looks saved and changes nothing."""
    with pytest.raises(env_file.UnknownSettingError, match="GOOGLE_APIKEY"):
        env_file.write_values({"GOOGLE_APIKEY": "oops"})


def test_a_refused_write_leaves_the_file_alone(env: Path) -> None:
    before = env.read_text(encoding="utf-8")
    with pytest.raises(env_file.UnknownSettingError):
        env_file.write_values({"SLEEPER_USERNAME": "valid", "NOT_A_SETTING": "x"})
    assert env.read_text(encoding="utf-8") == before


def test_an_empty_value_clears_the_key(env: Path) -> None:
    """`KEY=` is how people write "I do not use this", and AppSettings agrees."""
    env_file.write_values({"SLEEPER_USERNAME": ""})
    assert env_file.read_values()["SLEEPER_USERNAME"] == ""


def test_a_file_that_does_not_exist_yet_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    monkeypatch.setattr(env_file, "reload_settings", lambda: None)

    env_file.write_values({"FPL_ENTRY_ID": "99"})

    assert path.exists()
    assert env_file.read_values() == {"FPL_ENTRY_ID": "99"}


# ── values a bare dotenv line cannot carry ──────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["two words", "has#hash", 'has"quote', "back\\slash", "$dollar", "  padded  "],
)
def test_an_awkward_value_survives_a_round_trip(env: Path, value: str) -> None:
    env_file.write_values({"SLEEPER_USERNAME": value})
    assert env_file.read_values()["SLEEPER_USERNAME"] == value


def test_an_ordinary_value_is_not_needlessly_quoted(env: Path) -> None:
    """So a file edited here still reads like one edited by hand."""
    env_file.write_values({"SLEEPER_USERNAME": "abhibeast"})
    assert "SLEEPER_USERNAME=abhibeast" in env.read_text(encoding="utf-8")


# ── the shell wins ──────────────────────────────────────────────────────


def test_a_shell_variable_is_reported_as_shadowing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise an edit that cannot take effect looks like one that did."""
    monkeypatch.setenv("FPL_ENTRY_ID", "999")
    assert env_file.is_shadowed("FPL_ENTRY_ID")
    assert not env_file.is_shadowed("SLEEPER_USERNAME")


# ── reloading ───────────────────────────────────────────────────────────


def test_reload_mutates_the_singleton_every_module_already_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rebinding would leave every `from ... import settings` on the old object.

    Read from a file of the test's own, and with every field recorded first so
    the reload cannot carry the developer's real `.env` into the rest of the suite.
    """
    from thefrontoffice.config.settings import AppSettings

    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=fresh-name\n", encoding="utf-8")
    monkeypatch.setitem(AppSettings.model_config, "env_file", path)
    monkeypatch.delenv("SLEEPER_USERNAME", raising=False)
    for field in AppSettings.model_fields:
        monkeypatch.setattr(settings, field, getattr(settings, field))
    before = settings
    monkeypatch.setattr(settings, "sleeper_username", "stale")

    env_file.reload_settings()

    assert settings is before
    assert settings.sleeper_username == "fresh-name"


def test_pydantic_reads_back_exactly_what_was_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract that actually matters.

    This module's own reader agreeing with its own writer proves nothing —
    pydantic-settings parses the file, so the round trip has to survive *its*
    parser, not ours.
    """
    from pydantic_settings import BaseSettings, SettingsConfigDict

    path = tmp_path / ".env"
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    monkeypatch.setattr(env_file, "reload_settings", lambda: None)
    awkward = 'two words #hash "quoted" back\\slash'
    env_file.write_values({"SLEEPER_USERNAME": awkward})

    class Probe(BaseSettings):
        model_config = SettingsConfigDict(env_file=path, extra="ignore")
        sleeper_username: str = ""

    assert Probe().sleeper_username == awkward


# ── how each setting should be edited ───────────────────────────────────


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("logfire_capture_prompts", "boolean"),
        ("fpl_entry_id", "integer"),
        ("yahoo_max_weekly_adds", "integer"),
        ("log_level", "choice"),
        ("sleeper_username", "text"),
        ("gemini_api_key", "text"),
    ],
)
def test_a_field_declares_the_control_it_needs(field: str, kind: str) -> None:
    assert env_file.field_kind(field)[0] == kind


def test_optionality_does_not_change_what_kind_a_value_is() -> None:
    """`int | None` is still an integer; the None only says it may be absent."""
    assert env_file.field_kind("fpl_entry_id") == ("integer", [])


def test_a_choice_carries_its_allowed_values() -> None:
    assert env_file.field_kind("log_level")[1] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_a_boolean_writes_the_spelling_dotenv_reads_back(env: Path) -> None:
    env_file.write_values({"LOGFIRE_CAPTURE_PROMPTS": "true"})
    assert "LOGFIRE_CAPTURE_PROMPTS=true" in env.read_text(encoding="utf-8")
