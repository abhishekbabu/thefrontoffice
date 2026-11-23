"""Tests for how an FPL player reads as a row: his squad and market columns."""

from support.fpl import (
    DOUBTFUL_P3,
    LEAGUE_ID,
    MARKET,
    SQUAD_PLAYERS,
    player,
    provider,
)


def test_roster_rows_mark_the_captain_and_the_bench() -> None:
    rows = {c.columns["Player"]: c.columns for c in provider().roster(LEAGUE_ID)}
    assert rows["P8"]["Slot"] == "C"
    assert rows["P3"]["Slot"] == "XI"
    assert rows["P15"]["Slot"] == "BN"
    assert rows["P3"]["Price"] == "£5.0m"


def test_roster_rows_carry_each_players_worth_for_the_gameweek_to_come() -> None:
    """P3 projects 6.0 at home to a difficulty-2 side; P15's club blanks."""
    cards = {c.columns["Player"]: c for c in provider().roster(LEAGUE_ID)}

    assert (cards["P3"].columns["Worth"], cards["P15"].columns["Worth"]) == ("6.6", "0.0")


def test_roster_rows_report_a_doubt() -> None:
    cards = {c.columns["Player"]: c for c in provider(players=DOUBTFUL_P3).roster(LEAGUE_ID)}
    assert cards["P3"].columns["Status"] == "doubtful 50%"
    assert not cards["P3"].ruled_out  # a doubt is flagged, not counted out


def test_roster_rows_say_who_is_ruled_out() -> None:
    players = {**SQUAD_PLAYERS, 3: player(3, "DEF", 6.0, status="i", chance_of_playing=0), **MARKET}
    cards = {c.columns["Player"]: c for c in provider(players=players).roster(LEAGUE_ID)}
    assert cards["P3"].ruled_out
