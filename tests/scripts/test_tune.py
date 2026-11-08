"""Tests for the range-settings search: `scripts/tune.py`."""

from collections.abc import Mapping, Sequence

import pytest
import tune
from support.simulation import FakeForecast
from support.wiring import FakeCompetition, entry

from thefrontoffice.bootstrap import Registry
from thefrontoffice.domain.models import Outcomes, RangeSearch

SEARCH = RangeSearch(current={"spread": 1.0}, grid={"spread": (1.0, 4.0)})


class _Tunable(FakeForecast, FakeCompetition):
    """Ranges as wide as `spread` around 10 points, for players who all then score 12."""

    weeks: tuple[int, ...] = (2, 3, 4)

    def __init__(self) -> None:
        super().__init__()
        self.ranged: list[list[Mapping[str, float]]] = []

    def range_search(self) -> RangeSearch:
        return SEARCH

    def ranged_games(
        self, league_id: str, weeks: Sequence[int], candidates: Sequence[Mapping[str, float]]
    ) -> list[list[tuple[Outcomes, float]]]:
        self.ranged.append(list(candidates))
        return [
            [
                (Outcomes("p", "P", 10.0, tuple(10.0 + c["spread"] * (i - 5) / 5 for i in range(11))), 12.0)
                for _ in weeks
            ]
            for c in candidates
        ]


class _NoLeagues(_Tunable):
    leagues = ()


def test_the_setting_that_holds_what_players_scored_is_recommended(capsys: pytest.CaptureFixture[str]) -> None:
    assert tune.run(Registry((entry(_Tunable()),)), "nfl-sleeper") == 0
    assert "Recommend: {'spread': 4.0}" in capsys.readouterr().out


def test_every_week_is_read_once_for_all_the_candidates() -> None:
    provider = _Tunable()

    tune.run(Registry((entry(provider),)), "nfl-sleeper")

    assert len(provider.ranged) == 2  # the training weeks, then the held-out one


def test_an_account_with_no_league_says_so_rather_than_crashing(capsys: pytest.CaptureFixture[str]) -> None:
    assert tune.run(Registry((entry(_NoLeagues()),)), "nfl-sleeper") == 1
    assert "no NFL (Sleeper) league" in capsys.readouterr().out


def test_a_competition_whose_ranges_cannot_be_tuned_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert tune.run(Registry((entry(FakeCompetition()),)), "nfl-sleeper") == 1
    assert "does not support" in capsys.readouterr().out
