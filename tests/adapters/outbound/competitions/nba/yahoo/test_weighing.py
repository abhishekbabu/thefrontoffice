"""Tests for the week weighed: `nba/yahoo/weighing.py`."""

from dataclasses import replace

from support.nba import DEFAULT_TEAMS, FakeYahoo, make_player

from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, POINTS
from thefrontoffice.adapters.outbound.competitions.nba.worth import scales
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.weighing import open_reserve, season_standing
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory

CATS = (StatCategory(POINTS.yahoo_stat, "PTS"), StatCategory(BLOCKS.yahoo_stat, "BLK"))
FOUND = scales(CATS, [{POINTS.label: 10.0, BLOCKS.label: 0.0}, {POINTS.label: 30.0, BLOCKS.label: 2.0}])


def _league(mine: tuple[str, str], *others: tuple[str, str]) -> FakeYahoo:
    """A league whose teams print these season totals: points, then blocks; yours first."""
    yahoo = FakeYahoo()
    totals = [mine, *others]
    yahoo.league_teams = [
        replace(team, is_mine=at == 0, season={POINTS.yahoo_stat: pts, BLOCKS.yahoo_stat: blk})
        for at, (team, (pts, blk)) in enumerate(zip(_teams(len(totals)), totals, strict=True))
    ]
    return yahoo


def _teams(n: int) -> list:
    return [replace(DEFAULT_TEAMS[0], team_key=f"t.{i}", name=f"Team {i}") for i in range(n)]


def test_the_rosters_needs_rank_its_season_against_the_leagues_other_teams() -> None:
    yahoo = _league(("3600", "100"), ("3400", "150"), ("3300", "140"), ("3200", "130"))

    standing = season_standing(yahoo, FOUND)

    assert standing["PTS"] > 0 > standing["BLK"]


def test_without_the_standings_the_needs_have_no_league_to_rank_against() -> None:
    yahoo = _league(("3600", "100"), ("3400", "150"), ("3300", "140"), ("3200", "130"))
    yahoo.standings_error = YahooAPIError("down")

    assert season_standing(yahoo, FOUND) == {}
    assert season_standing(_league(("3600", "100")), {}) == {}


def test_the_injured_slots_open_are_those_the_settings_give_that_nobody_holds() -> None:
    held = [make_player("Hurt", "PF,C", "OKC", key="hurt", selected_position="IL")]

    assert open_reserve({"PG": 1, "IL": 2, "IL+": 1}, held) == ("IL", "IL+")
    assert open_reserve({"PG": 1, "IL": 1}, held) == ()
    assert open_reserve({"PG": 1}, []) == ()
