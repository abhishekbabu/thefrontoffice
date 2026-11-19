"""Tests for fitting and checking basketball's category odds: `scripts/calibrate_nba.py`."""

import calibrate_nba
import pytest
from support.nba import FakeOddsTuning

from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import ODDS_MODELS


def test_the_fit_is_checked_under_every_model_on_the_season_fitted_and_the_one_being_played() -> None:
    tuning = FakeOddsTuning()

    assert calibrate_nba.run(tuning) == 0
    assert tuning.checked == [(season, model) for season in ("2025", "2026") for model in ODDS_MODELS]


def test_the_fit_and_each_checks_score_are_printed(capsys: pytest.CaptureFixture[str]) -> None:
    calibrate_nba.run(FakeOddsTuning(brier={"hand-set": 0.2134, "fitted, independent": 0.2, "fitted": 0.1987}))

    out = capsys.readouterr().out
    assert "3744 player-weeks of the 2025 season" in out
    assert "Brier 0.2134" in out and "Brier 0.1987" in out
    assert "90%→80% (10)" in out


def test_a_season_with_nothing_to_fit_on_is_reported_rather_than_crashing(capsys: pytest.CaptureFixture[str]) -> None:
    assert calibrate_nba.run(FakeOddsTuning(error=NotFoundError("a week of the 2025 season to fit odds on"))) == 1
    assert "2025 season" in capsys.readouterr().out
