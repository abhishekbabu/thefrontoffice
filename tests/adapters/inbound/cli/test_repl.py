"""Tests for the REPL: parsing a line, and routing it to its command."""

import pytest
from support.wiring import FakeCompetition, entry, wiring

from thefrontoffice.adapters.inbound.cli.repl import QuitRequested, dispatch, parse_command
from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.domain.models import Stat, Summary


def test_command_token_is_case_insensitive() -> None:
    assert parse_command("/SCOUT")[0] == "/scout"
    assert parse_command("/Rosters")[0] == "/rosters"


def test_argument_casing_is_preserved() -> None:
    """Player-name lookups depend on casing, so only the command token is lowercased."""
    cmd, args = parse_command("/trade Give LeBron James, Get Jayson Tatum")
    assert cmd == "/trade"
    assert args == ["Give", "LeBron", "James,", "Get", "Jayson", "Tatum"]


def test_flags_are_stripped_from_arguments() -> None:
    """A flag is never part of a trade description or a competition's name."""
    cmd, args = parse_command("/trade --verbose Give LeBron")
    assert cmd == "/trade"
    assert args == ["Give", "LeBron"]


def test_empty_input_yields_empty_command() -> None:
    assert parse_command("") == ("", [])
    assert parse_command("   ") == ("", [])


# ── dispatch ────────────────────────────────────────────────────────────


def test_quit_raises_the_sentinel() -> None:
    with pytest.raises(QuitRequested):
        dispatch(Session(wiring()), "/quit", [])


def test_unknown_command_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    dispatch(Session(wiring()), "/nonsense", [])
    assert "/nonsense" in capsys.readouterr().out


class _Week(FakeCompetition):
    def summary(self, league_id: str) -> Summary:
        return Summary(headline=[Stat(label="Lineup", value="123.5")])


def test_week_is_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    dispatch(Session(wiring(entry(_Week()))), "/week", [])

    assert "123.5" in capsys.readouterr().out


def test_help_is_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    dispatch(Session(wiring(entry(_Week()))), "/help", [])

    assert "/roster" in capsys.readouterr().out
