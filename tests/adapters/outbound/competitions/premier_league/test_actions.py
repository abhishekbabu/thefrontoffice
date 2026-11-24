"""Tests for what an FPL gameweek asks of the manager: swaps, the armband, the bench, transfers and chips.

Every fixture here is of average difficulty, so a player's worth is his projection and the
arithmetic can be read straight off the fake squad (`support.fpl`).
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from support.fpl import BENCH_IDS, MARKET, SQUAD_PLAYERS, STARTING_IDS, player

from thefrontoffice.adapters.outbound.competitions.premier_league import actions
from thefrontoffice.adapters.outbound.competitions.premier_league.actions import Plan
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import best_lineup, plays, roster
from thefrontoffice.adapters.outbound.competitions.premier_league.worth import valuation
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Chip,
    ChipPlay,
    Fixture,
    Gameweek,
    Pick,
    Player,
    Squad,
)
from thefrontoffice.domain.models import Action

AVERAGE_WEEK = [
    Fixture(event=5, home="ARS", away="LIV", home_difficulty=3, away_difficulty=3),
    Fixture(event=5, home="MCI", away="TOT", home_difficulty=3, away_difficulty=3),
]

# A squad whose eleven as set is already the best: P15 and P14 are no better than the starters they sit behind.
SETTLED = {
    12: player(12, "MID", 0.4),
    14: player(14, "FWD", 0.4),
    15: player(15, "FWD", 0.3, team="MCI"),
}


def _squad(*, captain: int = 8, vice: int = 3, bank: int = 30) -> Squad:
    picks = [
        Pick(
            element=pid,
            position=i,
            multiplier=2 if pid == captain else 1,
            is_captain=pid == captain,
            is_vice_captain=pid == vice,
        )
        for i, pid in enumerate(STARTING_IDS, start=1)
    ]
    picks += [Pick(element=pid, position=i, multiplier=0) for i, pid in enumerate(BENCH_IDS, start=12)]
    return Squad(gameweek=4, picks=picks, bank=bank, value=1004)


def _items(
    changed: Mapping[int, Player] | None = None,
    *,
    captain: int = 8,
    vice: int = 3,
    bank: int = 30,
    allowance: int = 1,
    market: Mapping[int, Player] | None = None,
    weeks: Mapping[int, list[Fixture]] | None = None,
    upcoming: int = 5,
    chips: list[Chip] | None = None,
    played: list[ChipPlay] | None = None,
    untouchable: frozenset[str] = frozenset(),
) -> list[Action]:
    """The to-do list for the fake squad with `changed` players swapped into the catalog."""
    catalog = {**SQUAD_PLAYERS, **(market if market is not None else MARKET), **(changed or {})}
    value = valuation(catalog, {}, weeks or {upcoming: AVERAGE_WEEK}, played=0)
    mine = roster(_squad(captain=captain, vice=vice, bank=bank), catalog)
    owned = {p.id for p in mine.players}
    plan = Plan(
        roster=mine,
        value=value,
        upcoming=Gameweek(id=upcoming, name=f"Gameweek {upcoming}", deadline=datetime(2026, 9, 12, tzinfo=UTC)),
        allowance=allowance,
        selling={},
        market=sorted((p for p in catalog.values() if p.id not in owned and plays(p)), key=lambda p: -value(p)),
        chips=chips or [],
        played=played or [],
        untouchable=untouchable,
    )
    return actions.build(plan, best_lineup(mine.players, value))


def _of(items: list[Action], kind: str) -> list[Action]:
    return [item for item in items if item.kind == kind]


def _armbands(items: list[Action]) -> list[Action]:
    return [item for item in items if item.key.startswith("armband:")]


def _starts(items: list[Action]) -> list[Action]:
    return [item for item in items if item.key.startswith("start:")]


# ── the eleven ──────────────────────────────────────────────────────────


def test_a_bench_player_worth_more_starts_over_the_weakest_starter() -> None:
    [start] = _starts(_items())

    assert (start.player_id, start.replaces, start.urgency) == ("15", "7", "soon")


def test_a_swap_gaining_less_than_the_margin_is_left_alone() -> None:
    """P14 at 0.8 over P7 at 0.5 gains less than half a point."""
    assert _starts(_items({**SETTLED, 14: player(14, "FWD", 0.8)})) == []


def test_a_starter_ruled_out_is_swapped_however_small_the_gain() -> None:
    items = _items({**SETTLED, 7: player(7, "DEF", 0.5, status="i")})

    [start] = _starts(items)
    assert (start.player_id, start.replaces, start.urgency) == ("14", "7", "now")


def test_a_starter_whose_club_blanks_is_swapped_first() -> None:
    blanking = player(13, "FWD", 7.5, team="CHE")

    [start] = [item for item in _starts(_items({13: blanking})) if item.replaces == "13"]
    assert (start.player_id, start.urgency) == ("15", "now")


# ── the armband ─────────────────────────────────────────────────────────


def test_the_armband_moves_to_the_best_captain_with_a_vice_behind_him() -> None:
    [armband] = _armbands(_items())

    assert armband.player_id == "15"
    assert [(p.side, p.player_id) for p in armband.players] == [("in", "15"), ("in", "8"), ("out", "8")]


def test_a_captain_a_shade_behind_the_best_keeps_the_armband() -> None:
    assert _armbands(_items({**SETTLED, 9: player(9, "MID", 8.3)})) == []


def test_a_captain_unlikely_to_play_loses_the_armband_at_once() -> None:
    doubtful = player(8, "MID", 8.0, status="d", chance_of_playing=50)

    [armband] = _armbands(_items({**SETTLED, 8: doubtful}))
    assert (armband.player_id, armband.urgency) == ("13", "now")  # P13 at 7.5, the best of the rest


def test_a_vice_unlikely_to_play_is_replaced_though_the_captain_stays() -> None:
    doubtful = player(3, "DEF", 6.0, status="d", chance_of_playing=25)

    [armband] = _armbands(_items({**SETTLED, 3: doubtful}))
    assert [(p.side, p.player_id) for p in armband.players] == [("in", "8"), ("in", "13")]


def test_an_armband_set_right_asks_for_nothing() -> None:
    assert _armbands(_items(SETTLED, vice=9)) == []


# ── the bench ───────────────────────────────────────────────────────────


def test_a_first_substitute_who_will_not_play_goes_behind_one_who_will() -> None:
    [move] = _of(_items({**SETTLED, 12: player(12, "MID", 0.4, status="i")}), "lineup")

    assert (move.player_id, move.replaces) == ("14", "12")


def test_a_first_substitute_who_will_play_stays_first() -> None:
    assert _of(_items(SETTLED, vice=9), "lineup") == []


# ── transfers ───────────────────────────────────────────────────────────


def test_an_upgrade_the_bank_can_pay_for_is_a_free_transfer() -> None:
    [transfer] = _of(_items(SETTLED), "transfer")

    assert (transfer.player_id, transfer.drop, transfer.urgency) == ("100", "7", "soon")


def test_an_untouchable_player_is_never_sold() -> None:
    assert all(t.drop != "7" for t in _of(_items(SETTLED, untouchable=frozenset({"7"})), "transfer"))


def test_nothing_the_bank_cannot_pay_for_is_offered() -> None:
    assert _of(_items(SETTLED, bank=0), "transfer") == []


def test_a_transfer_beyond_the_free_ones_must_clear_its_hit_by_the_margin() -> None:
    """P100 is worth 6.5 more than P7: clear of a four-point hit by more than two."""
    assert len(_of(_items(SETTLED, allowance=0), "transfer")) == 1
    assert (
        _of(_items(SETTLED, allowance=0, market={100: player(100, "DEF", 5.0, cost=55, team="LIV")}), "transfer") == []
    )


def test_no_hit_is_taken_to_upgrade_a_player_the_best_eleven_benches() -> None:
    """P15 starts over P7, so a better defender for P7 would sit on the bench."""
    assert _of(_items(allowance=0), "transfer") == []


def test_a_starter_in_trouble_no_bench_swap_covers_is_transferred_out_first() -> None:
    keepers = {1: player(1, "GKP", 4.0, status="i"), 2: player(2, "GKP", 1.0, team="MCI", status="i")}
    market = {**MARKET, 105: player(105, "GKP", 3.0, cost=45, team="LIV")}

    first, *_ = _of(_items({**SETTLED, **keepers}, allowance=2, market=market), "transfer")
    assert (first.player_id, first.drop, first.urgency) == ("105", "1", "now")


def test_a_transfer_compares_both_players_at_the_price_each_changes_hands_for() -> None:
    [transfer] = _of(_items(SETTLED), "transfer")

    rows = [[figure.label for figure in p.figures] for p in transfer.players]
    prices = [next(f.value for f in p.figures if f.label == "Price") for p in transfer.players]
    assert rows[0] == rows[1]
    assert prices == ["£5.5m", "£5.0m"]


# ── chips ───────────────────────────────────────────────────────────────

FIRST_HALF = [Chip(name="bboost", start_event=1, stop_event=19), Chip(name="wildcard", start_event=2, stop_event=19)]


def _chip_weeks(double_in: int | None = None) -> dict[int, list[Fixture]]:
    weeks = {week: list(AVERAGE_WEEK) for week in range(17, 21)}
    if double_in is not None:
        weeks[double_in] = [
            *AVERAGE_WEEK,
            Fixture(event=double_in, home="ARS", away="CHE", home_difficulty=3, away_difficulty=3),
        ]
    return weeks


def test_a_chip_whose_window_closes_within_the_notice_is_a_to_do() -> None:
    chips = _of(_items(SETTLED, upcoming=17, weeks=_chip_weeks(), chips=FIRST_HALF), "chip")

    assert [(c.key, c.urgency) for c in chips] == [("chip:bboost:19", "soon"), ("chip:wildcard:19", "soon")]


def test_a_chip_in_its_last_gameweek_is_urgent() -> None:
    chips = _of(_items(SETTLED, upcoming=19, weeks={19: AVERAGE_WEEK}, chips=FIRST_HALF), "chip")

    assert {c.urgency for c in chips} == {"now"}


def test_a_chip_with_weeks_to_spare_or_already_played_is_not() -> None:
    assert _of(_items(SETTLED, chips=FIRST_HALF), "chip") == []
    played = [ChipPlay(name="bboost", event=3), ChipPlay(name="wildcard", event=4)]
    assert _of(_items(SETTLED, upcoming=17, weeks=_chip_weeks(), chips=FIRST_HALF, played=played), "chip") == []


def test_a_double_gameweek_in_the_window_says_when_to_play_the_chip_it_suits() -> None:
    bench_boost, wildcard = _of(_items(SETTLED, upcoming=17, weeks=_chip_weeks(18), chips=FIRST_HALF), "chip")

    assert "GW18" in bench_boost.reason
    assert "GW18" not in wildcard.reason


def test_a_blank_for_the_squads_clubs_says_when_to_play_a_free_hit() -> None:
    weeks = _chip_weeks()
    weeks[18] = [Fixture(event=18, home="LIV", away="TOT", home_difficulty=3, away_difficulty=3)]
    [free_hit] = _of(
        _items(SETTLED, upcoming=17, weeks=weeks, chips=[Chip(name="freehit", start_event=2, stop_event=19)]), "chip"
    )

    assert "GW18" in free_hit.reason
