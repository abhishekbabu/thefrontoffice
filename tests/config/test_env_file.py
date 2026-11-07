"""Tests for editing `.env` in place.

This module writes the file that holds every credential, so the assertions are
mostly about what it must not do: invent keys, lose comments, or mangle a value
on the way back out.
"""

from pathlib import Path

import pytest

from thefrontoffice.config import env_file
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import AppSettings

TEMPLATE = """# Yahoo credentials
YAHOO_CLIENT_ID=abc
YAHOO_CLIENT_SECRET=

# Sleeper — no key needed
SLEEPER_USERNAME=abhibeast
LOG_LEVEL=INFO
"""


def _env(path: Path) -> EnvFile:
    """The file at `path`, configuring settings of the test's own rather than the process's."""
    return EnvFile(path, settings=AppSettings(_env_file=None))


@pytest.fixture
def env(tmp_path: Path) -> EnvFile:
    path = tmp_path / ".env"
    path.write_text(TEMPLATE, encoding="utf-8")
    return _env(path)


# ── reading ─────────────────────────────────────────────────────────────


def test_values_are_read_in_file_order(env: EnvFile) -> None:
    assert list(env.read_values()) == [
        "YAHOO_CLIENT_ID",
        "YAHOO_CLIENT_SECRET",
        "SLEEPER_USERNAME",
        "LOG_LEVEL",
    ]


def test_comments_are_not_keys(env: EnvFile) -> None:
    assert "# Yahoo credentials" not in env.read_values()


def test_a_missing_file_reads_as_empty(tmp_path: Path) -> None:
    assert _env(tmp_path / "absent").read_values() == {}


def test_a_quoted_value_reads_back_unquoted(env: EnvFile) -> None:
    env.path.write_text('SLEEPER_USERNAME="two words"\n', encoding="utf-8")
    assert env.read_values()["SLEEPER_USERNAME"] == "two words"


# ── writing ─────────────────────────────────────────────────────────────


def test_an_existing_key_is_replaced_in_place(env: EnvFile) -> None:
    env.write_values({"SLEEPER_USERNAME": "someone-else"})
    assert env.read_values()["SLEEPER_USERNAME"] == "someone-else"


def test_comments_and_ordering_survive_a_write(env: EnvFile) -> None:
    """The file is a person's, not this app's — regenerating it would lose that."""
    env.write_values({"SLEEPER_USERNAME": "someone-else"})
    text = env.path.read_text(encoding="utf-8")

    assert "# Yahoo credentials" in text
    assert "# Sleeper — no key needed" in text
    assert text.index("YAHOO_CLIENT_ID") < text.index("SLEEPER_USERNAME")


def test_a_new_key_is_appended(env: EnvFile) -> None:
    env.write_values({"FPL_ENTRY_ID": "12345"})
    assert env.read_values()["FPL_ENTRY_ID"] == "12345"


def test_an_untouched_key_keeps_its_value(env: EnvFile) -> None:
    env.write_values({"FPL_ENTRY_ID": "12345"})
    assert env.read_values()["YAHOO_CLIENT_ID"] == "abc"


def test_a_key_no_setting_reads_is_refused(env: EnvFile) -> None:
    """A line nothing picks up looks saved and changes nothing."""
    with pytest.raises(env_file.UnknownSettingError, match="GOOGLE_APIKEY"):
        env.write_values({"GOOGLE_APIKEY": "oops"})


def test_a_refused_write_leaves_the_file_alone(env: EnvFile) -> None:
    before = env.path.read_text(encoding="utf-8")
    with pytest.raises(env_file.UnknownSettingError):
        env.write_values({"SLEEPER_USERNAME": "valid", "NOT_A_SETTING": "x"})
    assert env.path.read_text(encoding="utf-8") == before


def test_an_empty_value_clears_the_key(env: EnvFile) -> None:
    """`KEY=` is how people write "I do not use this", and AppSettings agrees."""
    env.write_values({"SLEEPER_USERNAME": ""})
    assert env.read_values()["SLEEPER_USERNAME"] == ""


def test_a_file_that_does_not_exist_yet_is_created(tmp_path: Path) -> None:
    env = _env(tmp_path / ".env")

    env.write_values({"FPL_ENTRY_ID": "99"})

    assert env.path.exists()
    assert env.read_values() == {"FPL_ENTRY_ID": "99"}


# ── values a bare dotenv line cannot carry ──────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["two words", "has#hash", 'has"quote', "back\\slash", "$dollar", "  padded  "],
)
def test_an_awkward_value_survives_a_round_trip(env: EnvFile, value: str) -> None:
    env.write_values({"SLEEPER_USERNAME": value})
    assert env.read_values()["SLEEPER_USERNAME"] == value


def test_an_ordinary_value_is_not_needlessly_quoted(env: EnvFile) -> None:
    """So a file edited here still reads like one edited by hand."""
    env.write_values({"SLEEPER_USERNAME": "abhibeast"})
    assert "SLEEPER_USERNAME=abhibeast" in env.path.read_text(encoding="utf-8")


# ── the shell wins ──────────────────────────────────────────────────────


def test_a_shell_variable_is_reported_as_shadowing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise an edit that cannot take effect looks like one that did."""
    monkeypatch.setenv("FPL_ENTRY_ID", "999")
    assert env_file.is_shadowed("FPL_ENTRY_ID")
    assert not env_file.is_shadowed("SLEEPER_USERNAME")


# ── reloading ───────────────────────────────────────────────────────────


def test_a_write_refreshes_the_settings_every_module_already_holds(
    env: EnvFile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebinding would leave every `from ... import settings` on the old object."""
    monkeypatch.delenv("SLEEPER_USERNAME", raising=False)
    held = env.settings

    env.write_values({"SLEEPER_USERNAME": "fresh-name"})

    assert env.settings is held
    assert held.sleeper_username == "fresh-name"


def test_pydantic_reads_back_exactly_what_was_written(tmp_path: Path) -> None:
    """The contract that actually matters.

    This module's own reader agreeing with its own writer proves nothing —
    pydantic-settings parses the file, so the round trip has to survive *its*
    parser, not ours.
    """
    from pydantic_settings import BaseSettings, SettingsConfigDict

    env = _env(tmp_path / ".env")
    awkward = 'two words #hash "quoted" back\\slash'
    env.write_values({"SLEEPER_USERNAME": awkward})

    class Probe(BaseSettings):
        model_config = SettingsConfigDict(env_file=env.path, extra="ignore")
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


def test_a_boolean_writes_the_spelling_dotenv_reads_back(env: EnvFile) -> None:
    env.write_values({"LOGFIRE_CAPTURE_PROMPTS": "true"})
    assert "LOGFIRE_CAPTURE_PROMPTS=true" in env.path.read_text(encoding="utf-8")


# ── describing a setting ────────────────────────────────────────────────


def test_a_secret_is_described_by_its_presence_alone(tmp_path: Path) -> None:
    """There is nothing a reader can do with the characters of an API key that it cannot do with the fact one is set."""
    env = EnvFile(tmp_path / ".env", settings=AppSettings(_env_file=None, groq_api_key="super-secret-value"))

    described = env.describe("groq_api_key", "super-secret-value")

    assert (described.secret, described.present) == (True, True)
    assert "super-secret-value" not in described.model_dump_json()


def test_a_non_secret_carries_what_the_file_holds(env: EnvFile) -> None:
    assert env.describe("sleeper_username", "abhibeast").value == "abhibeast"


def test_a_boolean_is_described_by_its_effective_value_not_the_file_text(tmp_path: Path) -> None:
    """An absent key and a false one look identical in the file, so the file text cannot say a setting is on."""
    env = EnvFile(tmp_path / ".env", settings=AppSettings(_env_file=None, logfire_capture_prompts=True))

    assert env.describe("logfire_capture_prompts").value == "true"


def test_a_default_in_force_is_not_described_as_unset(env: EnvFile) -> None:
    described = env.describe("log_level")

    assert (described.value, described.effective) == ("", "INFO")


def test_every_setting_is_described_under_a_group(env: EnvFile) -> None:
    """A setting the page has no group for would be unreachable there, with nothing to say so."""
    grouped = [setting.field for group in env.groups() for setting in group.settings]

    assert sorted(grouped) == sorted(AppSettings.model_fields)


def test_a_key_in_the_file_nothing_reads_is_unknown(env: EnvFile) -> None:
    env.path.write_text("GOOGLE_APIKEY=abc\nSLEEPER_USERNAME=someone\n", encoding="utf-8")

    assert env.unknown() == ["GOOGLE_APIKEY"]
