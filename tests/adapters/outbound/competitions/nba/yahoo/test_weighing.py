"""Tests for the week weighed: `nba/yahoo/weighing.py`."""

from dataclasses import replace
from datetime import UTC, date, datetime

from support.nba import DEFAULT_TEAMS, FakeYahoo, make_player
from support.stores import FakeDayLog

from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, POINTS
from thefrontoffice.adapters.outbound.competitions.nba.worth import scales
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import reads
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.weighing import (
    games_played,
    history,
    open_reserve,
    remembered,
    season_standing,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, Pairing, StatCategory

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

    standing = season_standing(yahoo, FOUND, week=6)

    assert standing["PTS"] > 0 > standing["BLK"]


def _played(*games: int) -> dict[int, list[Pairing]]:
    """Two weeks in which each team played these games, its own matchup each, by the order `_teams` names them."""
    sides = [
        MatchupSide(team_key=f"t.{i}", name=f"Team {i}", points="", stats={}, games=n) for i, n in enumerate(games)
    ]
    pairings = [
        Pairing(start=date(2026, 11, 2), end=date(2026, 11, 8), mine=a, opponent=b)
        for a, b in zip(sides[::2], sides[1::2], strict=True)
    ]
    return {1: pairings, 2: pairings}


def test_the_seasons_totals_are_read_a_game_played_at_a_time() -> None:
    """The most points, from the most games: per game, the fewest."""
    yahoo = _league(("3600", "100"), ("3400", "150"), ("3300", "140"), ("3200", "130"))
    yahoo.league_matchups = _played(110, 90, 90, 90)

    assert season_standing(yahoo, FOUND, week=2)["PTS"] < 0
    yahoo.matchups_error = YahooAPIError("down")
    assert season_standing(yahoo, FOUND, week=2)["PTS"] > 0  # as printed, without the games
    assert games_played(yahoo, 0) == {}


def test_without_the_standings_the_needs_have_no_league_to_rank_against() -> None:
    yahoo = _league(("3600", "100"), ("3400", "150"), ("3300", "140"), ("3200", "130"))
    yahoo.standings_error = YahooAPIError("down")

    assert season_standing(yahoo, FOUND, week=6) == {}
    assert season_standing(_league(("3600", "100")), {}, week=6) == {}
    nobody = _league(("3600", "100"), ("3400", "150"))
    nobody.league_teams = [replace(t, is_mine=False) for t in nobody.league_teams]
    assert season_standing(nobody, FOUND, week=6) == {}


def test_the_injured_slots_open_are_those_the_settings_give_that_nobody_holds() -> None:
    held = [make_player("Hurt", "PF,C", "OKC", key="hurt", selected_position="IL")]

    assert open_reserve({"PG": 1, "IL": 2, "IL+": 1}, held) == ("IL", "IL+")
    assert open_reserve({"PG": 1, "IL": 1}, held) == ()
    assert open_reserve({"PG": 1}, []) == ()


def test_each_report_is_kept_as_seen_and_its_body_part_outlives_it() -> None:
    """Monday's report kept; on a day ESPN no longer lists him, the hip is what his history remembers."""
    caruso = make_player("Alex Caruso", "SG", "OKC", key="caruso")
    log = FakeDayLog()
    hip = InjuryReport(
        name="Alex Caruso",
        club="OKC",
        status="Out",
        updated=datetime(2026, 11, 18, tzinfo=UTC),
        injury="Left hip, soreness",
    )

    kept, rests = history(log, [caruso], reads.injuries([caruso], [hip]), date(2026, 11, 16))
    later, _ = history(log, [caruso], reads.injuries([caruso], []), date(2026, 11, 16))

    assert [h.injury for h in kept["caruso"]] == ["Left hip, soreness"]
    assert remembered(later, caruso) == "Left hip, soreness"
    assert remembered({}, caruso) == ""
    assert not rests["caruso"](date(2026, 11, 17), True)
    assert history(None, [caruso], reads.injuries([caruso], [hip]), date(2026, 11, 16)) == ({}, {})
