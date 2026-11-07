"""Tests for terminal output: tables and errors."""

import pytest

from thefrontoffice.adapters.inbound.cli import output
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError


def test_rows_are_printed_with_aligned_columns(capsys: pytest.CaptureFixture[str]) -> None:
    output.rows([{"Player": "A", "Pos": "QB"}, {"Player": "Longer Name", "Pos": "RB"}])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len({len(ln.rstrip()) for ln in lines}) <= 2  # header, rule and rows align


def test_an_empty_roster_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """Rather than printing nothing, which reads as a hang or a crash."""
    output.rows([])
    assert capsys.readouterr().out.strip()


def test_an_error_the_terminal_can_fix_names_the_fix(capsys: pytest.CaptureFixture[str]) -> None:
    output.print_error(YahooLoginRequiredError(), "NBA (Yahoo)")

    out = capsys.readouterr().out
    assert "NBA (Yahoo)" in out and "just yahoo-login" in out
