"""Tests for the matchup backtest's entry point: `scripts/backtest.py`."""

import backtest
import pytest
from support.simulation import FakeForecast
from support.wiring import FakeCompetition, entry

from thefrontoffice.bootstrap import Registry


class _Forecasts(FakeForecast, FakeCompetition):
    pass


class _NoLeagues(_Forecasts):
    leagues = ()


def test_an_account_with_no_league_says_so_rather_than_crashing(capsys: pytest.CaptureFixture[str]) -> None:
    assert backtest.run(Registry((entry(_NoLeagues()),)), "nfl-sleeper") == 1
    assert "no NFL (Sleeper) league" in capsys.readouterr().out


def test_a_season_with_no_finished_week_has_nothing_to_score(capsys: pytest.CaptureFixture[str]) -> None:
    assert backtest.run(Registry((entry(_Forecasts()),)), "nfl-sleeper") == 1
    assert "No finished week" in capsys.readouterr().out


def test_a_competition_that_cannot_simulate_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert backtest.run(Registry((entry(FakeCompetition()),)), "nfl-sleeper") == 1
    assert "does not support" in capsys.readouterr().out
