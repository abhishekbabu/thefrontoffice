"""Tests for the nights a daily lineup would start each player: `nba/lineup.py`."""

from datetime import date

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.lineup import (
    Week,
    needed_nights,
    open_nights,
    seated,
    slots,
    starts,
    streamed,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer

MON, TUE, WED, THU = (date(2026, 11, day) for day in (23, 24, 25, 26))


def _games(*nights: tuple[date, str, str]) -> list[ScheduledGame]:
    return [ScheduledGame(week=0, date=day.isoformat(), home=home, away=away) for day, home, away in nights]


def _player(name: str, position: str, team: str, slot: str = "BN", status: str = "") -> YahooPlayer:
    return make_player(name, position=position, team=team, key=name, selected_position=slot, status=status)


GAMES = _games((MON, "LAL", "BOS"), (MON, "DEN", "MIA"), (TUE, "DEN", "NYK"), (WED, "LAL", "NYK"))
"""Monday the Lakers, Celtics, Nuggets and Heat play; Tuesday the Nuggets and Knicks; Thursday nobody."""


def _week(*lineup: str) -> Week:
    return Week(games=GAMES, slots=lineup, today=MON, end=date(2026, 11, 29))


def test_the_settings_slots_expand_to_one_per_place_leaving_out_the_bench_and_injured_ones() -> None:
    assert slots({"PG": 1, "C": 2, "Util": 1, "BN": 3, "IL": 2, "IL+": 1}) == ("PG", "C", "C", "Util")


def test_players_are_seated_in_whatever_arrangement_starts_the_most() -> None:
    """A guard who can play forward moves over so a pure forward fits too."""
    flexible, forward = _player("Flex", "SG,SF", "LAL"), _player("Forward", "SF", "BOS")

    assert seated([flexible, forward], ("SF", "G")) == 2
    assert seated([flexible, forward], ("SF",)) == 1
    assert seated([_player("Center", "C", "LAL")], ("PG", "SG")) == 0


def test_a_pickup_counts_only_the_nights_his_position_finds_an_open_slot() -> None:
    """Monday the lone forward slot is taken; Tuesday it is free."""
    starter = _player("Starter", "SF", "LAL", "SF")
    pickup = _player("Pickup", "SF", "DEN")

    assert open_nights(pickup, [starter], _week("SF"), {}) == [TUE]
    assert open_nights(pickup, [starter], _week("SF", "Util"), {}) == [MON, TUE]
    assert open_nights(_player("Center", "C", "DEN"), [starter], _week("SF"), {}) == []


def test_a_hurt_player_holds_no_slot_until_he_is_back() -> None:
    hurt = _player("Hurt", "SF", "LAL", "SF", status="O")
    pickup = _player("Pickup", "SF", "LAL")

    assert open_nights(pickup, [hurt], _week("SF"), {"Hurt": WED}) == [MON]
    assert open_nights(pickup, [hurt], _week("SF"), {}) == [MON, WED]


def test_a_drop_costs_the_nights_nobody_else_could_take_his_slot() -> None:
    """Monday both play for one slot, so either could go; Wednesday only the Laker plays, Tuesday the Nugget."""
    lakers, nuggets = _player("Laker", "SF", "LAL", "SF"), _player("Nugget", "SF", "DEN", "BN")

    assert needed_nights(lakers, [lakers, nuggets], _week("SF"), {}) == [WED]
    assert needed_nights(nuggets, [lakers, nuggets], _week("SF"), {}) == [TUE]
    assert needed_nights(_player("Hurt", "SF", "LAL", "IL"), [lakers], _week("SF"), {}) == []


def test_a_roster_starts_each_night_as_many_as_its_slots_seat() -> None:
    """Monday three play for two slots; Tuesday one; Wednesday one: four games, the injured list's none."""
    roster = [
        _player("Laker", "SF", "LAL", "SF"),
        _player("Celtic", "SF", "BOS", "BN"),
        _player("Nugget", "C", "DEN", "C"),
        _player("Injured", "C", "MIA", "IL", status="O"),
    ]

    assert starts(roster, _week("SF", "C"), {}) == 4


def test_the_days_without_games_before_a_return_are_the_free_adds() -> None:
    assert _week("SF").quiet(date(2026, 11, 28)) == [THU, date(2026, 11, 27)]
    assert _week("SF").quiet(THU) == []


def test_a_sides_adds_left_could_stream_in_the_starts_its_open_slots_leave() -> None:
    """SF and Util with one Laker: a Knick fills Tuesday and Wednesday, then a Nugget Monday and Tuesday; a Celtic
    finds Monday full by then."""
    roster = [_player("Starter", "SF", "LAL", "SF")]
    wire = [_player("Knick", "SF", "NYK"), _player("Nugget", "SF", "DEN"), _player("Celtic", "SF", "BOS")]
    wire.append(_player("Hurt", "SF", "MIA", status="O"))
    week = _week("SF", "Util")

    assert [streamed(roster, wire, week, {}, adds) for adds in (0, 1, 2, 3)] == [0, 2, 4, 4]
