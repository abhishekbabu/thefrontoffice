"""Tests for how a script picks the league it runs over: `scripts/leagues.py`."""

import pytest
from leagues import DEFAULT_KEY, chosen, first_league
from support.wiring import LEAGUE, FakeCompetition

from thefrontoffice.domain.errors import LeagueNotFoundError


class _NoLeagues(FakeCompetition):
    leagues = ()


def test_the_first_league_is_the_one_run_over() -> None:
    assert first_league(FakeCompetition(), "NFL (Sleeper)") == LEAGUE


def test_no_league_this_season_is_a_failure_that_names_the_competition() -> None:
    """It was `list_leagues()[0]`: an IndexError, with a traceback instead of a sentence."""
    with pytest.raises(LeagueNotFoundError, match="NFL"):
        first_league(_NoLeagues(), "NFL (Sleeper)")


def test_a_script_runs_over_the_competition_named_after_it_or_the_default() -> None:
    assert (chosen(["tune.py", "nba-yahoo"]), chosen(["tune.py"])) == ("nba-yahoo", DEFAULT_KEY)
