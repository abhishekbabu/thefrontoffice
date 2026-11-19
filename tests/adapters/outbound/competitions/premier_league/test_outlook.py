"""Tests for the gameweeks ahead: each squad player's run of fixtures, and the weeks that blank or double."""

from datetime import UTC, datetime

from support.fpl import SQUAD_PLAYERS, player

from thefrontoffice.adapters.outbound.competitions.premier_league.outlook import (
    outlook,
    run_of,
    ticker,
    weeks_from,
)
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import Roster, roster
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Pick, Player, Squad

WEEKS = [11, 12, 13, 14, 15]


def fixture(week: int | None, home: str, away: str, home_fdr: int = 3, away_fdr: int = 3, day: int = 1) -> Fixture:
    return Fixture(
        event=week,
        home=home,
        away=away,
        home_difficulty=home_fdr,
        away_difficulty=away_fdr,
        kickoff=datetime(2026, 11, day, 15, tzinfo=UTC),
    )


def squad_of(*players: int, catalog: dict[int, Player] | None = None) -> Roster:
    picks = [Pick(element=pid, position=i, multiplier=1) for i, pid in enumerate(players, start=1)]
    return roster(Squad(gameweek=10, picks=picks, bank=0, value=1000), catalog or SQUAD_PLAYERS)


# Arsenal play every week; Man City blank GW13 and double GW14.
SEASON = [
    *(fixture(w, "ARS", "LIV", 2, 4) for w in WEEKS),
    fixture(11, "MCI", "TOT"),
    fixture(12, "CHE", "MCI"),
    fixture(14, "MCI", "BOU", 2, 2, day=2),
    fixture(14, "NEW", "MCI", 4, 4, day=5),
    fixture(15, "MCI", "EVE"),
    fixture(None, "MCI", "FUL"),
]


def test_the_grid_covers_five_gameweeks_and_stops_at_the_seasons_end() -> None:
    assert weeks_from(11, 38) == WEEKS
    assert weeks_from(36, 38) == [36, 37, 38]


def test_a_club_with_no_match_blanks_and_one_with_two_doubles_in_kickoff_order() -> None:
    run = run_of("MCI", WEEKS, ticker(SEASON))

    assert [len(w.games) for w in run] == [1, 1, 0, 2, 1]
    assert [(g.opponent, g.home, g.difficulty) for g in run[3].games] == [("BOU", True, 2), ("NEW", False, 4)]


def test_only_players_with_something_to_act_on_get_a_row() -> None:
    """A run of ordinary fixtures is a count, not a row a player saying so."""
    found = outlook(squad_of(1, 15), SEASON, WEEKS)  # P1 at Arsenal, P15 at Man City

    assert [run.player for run in found.runs] == ["P15"]
    assert found.runs[0].flags == ["blank GW13", "double GW14"]
    assert found.clear == 1


def test_a_hard_stretch_earns_a_row_and_one_hard_week_does_not() -> None:
    hard = [fixture(w, "LIV", "ARS", 3, 4 if w < 14 else 2) for w in WEEKS]
    found = outlook(squad_of(1), hard, WEEKS)
    assert found.runs[0].flags == ["3 hard"]

    one_hard = [fixture(w, "LIV", "ARS", 3, 4 if w == 11 else 2) for w in WEEKS]
    assert outlook(squad_of(1), one_hard, WEEKS).runs == []


def test_a_doubt_earns_a_row_whatever_his_fixtures() -> None:
    catalog = {**SQUAD_PLAYERS, 3: player(3, "DEF", 6.0, status="d", chance_of_playing=75)}
    found = outlook(squad_of(3, catalog=catalog), SEASON, WEEKS)

    assert found.runs[0].flags == ["doubtful 75%"]
    assert found.runs[0].detail == "DEF · ARS"


def test_the_weeks_a_blank_or_double_lands_on_the_squad_name_who() -> None:
    found = outlook(squad_of(1, 2, 15), SEASON, WEEKS)  # P2 and P15 both at Man City

    assert [(w.label, w.value, w.tone) for w in found.warnings] == [
        ("GW13", "2 blank: P2, P15", "warning"),
        ("GW14", "2 double: P2, P15", "good"),
    ]


def test_no_weeks_left_is_an_empty_outlook() -> None:
    found = outlook(squad_of(1), SEASON, [])
    assert (found.run_weeks, found.runs, found.clear) == ([], [], 0)
