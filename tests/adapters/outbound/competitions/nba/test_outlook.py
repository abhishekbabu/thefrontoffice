"""Tests for the basketball weeks ahead: `nba/outlook.py`."""

from dataclasses import replace
from datetime import date

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.outlook import Window, build
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer


def _window(week: int, days: dict[str, list[int]], first: int = 1) -> Window:
    """Week `week`, December `first` to `first + 6`, each club playing on the days of the month given."""
    games = [
        ScheduledGame(week=week, date=date(2026, 12, day).isoformat(), home=club, away=f"{club}2")
        for club, played in days.items()
        for day in played
    ]
    return Window(week=week, start=date(2026, 12, first), end=date(2026, 12, first + 6), games=games)


def _player(name: str, team: str, slot: str = "BN", status: str = "") -> YahooPlayer:
    return make_player(name, team=team, key=name, selected_position=slot, status=status)


def _readings(*valued: tuple[YahooPlayer, float]) -> dict[str, Reading]:
    return {p.player_key: Reading(player=p, line={}, per_game=value, games=None) for p, value in valued}


STAR = _player("Star", "AAA", "PG")
SECOND = _player("Second", "BBB", "C")
BENCH = _player("Bench", "CCC")


def test_a_week_counts_the_games_its_daily_lineups_can_start() -> None:
    """Two slots: on a day all three play, one of them sits."""
    window = _window(6, {"AAA": [1, 3], "BBB": [1, 4], "CCC": [1]})
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 10.0))

    outlook = build([window], [STAR, SECOND, BENCH], [], readings, {}, adds=3)

    assert outlook.measure == "games"
    assert outlook.weeks[0].points == 4  # two on the 1st, one each on the 3rd and 4th


def test_a_regular_with_two_games_is_light_and_a_bench_player_is_not_named() -> None:
    window = _window(6, {"AAA": [1, 3], "BBB": [1, 2, 4, 6], "CCC": [2]})
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 10.0))

    [week] = build([window], [STAR, SECOND, BENCH], [], readings, {}, adds=3).weeks

    assert week.light == ["Star (2 games)"]


def test_an_injured_player_says_when_he_is_back_and_what_the_week_keeps_of_him() -> None:
    window = _window(6, {"AAA": [1, 3, 5, 7], "BBB": [1, 4], "DDD": [2]})
    hurt = _player("Hurt", "AAA", "PG", status="O")
    unknown = _player("Unknown", "BBB", "IL", status="INJ")
    later = _player("Later", "DDD", "IL", status="O")
    readings = _readings((hurt, 40.0), (unknown, 30.0), (later, 20.0))
    returns = {"Hurt": date(2026, 12, 5), "Later": date(2027, 1, 2)}

    [week] = build([window], [hurt, unknown, later], [], readings, returns, adds=0).weeks

    assert week.missing == [
        "Hurt (O, back ~5 Dec: 2 of 4 games)",
        "Unknown (INJ, no return date)",
        "Later (O, back ~2 Jan)",
    ]


def test_a_week_well_below_the_usual_is_short_and_one_most_clubs_play_four_in_is_heavy() -> None:
    every = {"AAA": [1, 2, 3, 4], "BBB": [1, 2, 3, 4], "CCC": [1, 2, 3, 4]}
    thin = {"AAA": [1], "BBB": [2], "CCC": [3]}
    roster = [STAR, SECOND, BENCH]
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 10.0))

    outlook = build(
        [_window(6, every), _window(7, thin, first=8), _window(8, every, first=15)], roster, [], readings, {}, adds=0
    )

    assert outlook.usual == 8
    assert [(w.week, w.short, w.heavy) for w in outlook.weeks] == [(6, False, True), (7, True, False), (8, False, True)]
    assert outlook.weeks[1].short_by == 5


def _streamable() -> tuple[list[YahooPlayer], list[YahooPlayer], dict[str, Reading], Window]:
    """Four on the roster, the weakest playing twice, in a heavy week; a free agent playing four times."""
    weak = _player("Weak", "DDD")
    pickup = _player("Pickup", "EEE")
    roster = [STAR, SECOND, BENCH, weak]
    window = _window(
        6, {"AAA": [1, 3, 5, 7], "BBB": [1, 3, 5, 7], "CCC": [2, 4, 6], "DDD": [1, 2], "EEE": [1, 3, 5, 7]}
    )
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 12.0), (weak, 10.0), (pickup, 14.0))
    return roster, [pickup], readings, window


def test_a_free_agent_with_more_games_who_clears_the_margin_streams_in() -> None:
    roster, wire, readings, window = _streamable()

    [week] = build([window], roster, wire, readings, {}, adds=3).weeks

    assert "Pickup" in week.fix
    assert "drop Weak" in week.fix
    assert week.gain == 2  # four games for two


def test_an_untouchable_player_is_never_the_drop_for_a_week_ahead() -> None:
    roster, wire, readings, window = _streamable()

    [week] = build([window], roster, wire, readings, {}, adds=3, untouchable={"Weak"}).weeks

    assert "drop Weak" not in week.fix


def test_nothing_streams_without_adds_or_without_more_games() -> None:
    roster, wire, readings, window = _streamable()
    level = _window(6, {"AAA": [1, 3, 5, 7], "BBB": [1, 3, 5, 7], "CCC": [2, 4, 6], "DDD": [1, 2], "EEE": [1, 3]})

    assert build([window], roster, wire, readings, {}, adds=0).weeks[0].fix == ""
    assert build([level], roster, wire, readings, {}, adds=3).weeks[0].fix == ""


def test_a_night_counts_only_the_players_the_leagues_slots_seat() -> None:
    """Three forwards on the 1st, a lineup of one PF and one C: one starts, where a cap of two would start two."""
    window = _window(6, {"AAA": [1], "BBB": [1], "CCC": [1]})
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 10.0))

    fitted = build([window], [STAR, SECOND, BENCH], [], readings, {}, adds=0, lineup=("PF", "C"))
    capped = build([window], [STAR, SECOND, BENCH], [], readings, {}, adds=0)

    assert (fitted.weeks[0].points, capped.weeks[0].points) == (1, 2)


def test_a_stream_counts_only_the_nights_he_would_start_in_the_drops_place() -> None:
    """Two forward slots, both taken by Star and Second on every night the pickup plays: he would start none."""
    roster, wire, readings, window = _streamable()

    assert build([window], roster, wire, readings, {}, adds=3).weeks[0].fix != ""
    assert build([window], roster, wire, readings, {}, adds=3, lineup=("PF", "PF")).weeks[0].fix == ""
    [opened] = build([window], roster, wire, readings, {}, adds=3, lineup=("PF", "PF", "Util")).weeks
    assert opened.gain == 2  # four nights in an open slot for the two Weak is needed on


def test_a_pickup_is_named_in_one_week_only() -> None:
    roster, wire, readings, window = _streamable()
    again = _window(7, {club: [day + 7 for day in days] for club, days in _days(window).items()}, first=8)

    weeks = build([window, again], roster, wire, readings, {}, adds=3).weeks

    assert ["Pickup" in w.fix for w in weeks] == [True, False]


def _waiting(wire: list[YahooPlayer], cleared: date) -> list[YahooPlayer]:
    return [replace(p, waiver_date=cleared) for p in wire]


def test_a_player_on_waivers_counts_only_the_games_after_he_clears_them() -> None:
    """His club plays the 1st, 3rd, 5th and 7th; cleared on the 2nd, he has three of them, a game over the drop."""
    roster, wire, readings, window = _streamable()

    [week] = build([window], roster, _waiting(wire, date(2026, 12, 2)), readings, {}, adds=3).weeks

    assert week.fix.startswith("Claim Pickup")
    assert "clears 2 Dec" in week.fix
    assert "3 games" in week.fix
    assert week.gain == 1


def test_a_player_on_waivers_with_no_more_games_left_after_clearing_streams_nothing() -> None:
    roster, wire, readings, window = _streamable()

    [week] = build([window], roster, _waiting(wire, date(2026, 12, 4)), readings, {}, adds=3).weeks

    assert week.fix == ""


def test_a_player_clear_of_waivers_by_a_later_week_is_picked_up_in_it_not_claimed() -> None:
    roster, wire, readings, window = _streamable()
    again = _window(7, {club: [day + 7 for day in days] for club, days in _days(window).items()}, first=8)

    weeks = build([window, again], roster, _waiting(wire, date(2026, 12, 6)), readings, {}, adds=3).weeks

    assert weeks[0].fix == ""
    assert weeks[1].fix.startswith("Pick up Pickup")
    assert weeks[1].gain == 2


def _days(window: Window) -> dict[str, list[int]]:
    days: dict[str, list[int]] = {}
    for g in window.games:
        days.setdefault(g.home, []).append(int(g.date[-2:]))
    return days


def test_no_weeks_left_is_an_empty_outlook() -> None:
    assert build([], [STAR], [], {}, {}, adds=3).weeks == []


def test_a_week_still_being_scheduled_is_provisional_never_short_or_light_and_out_of_the_usual() -> None:
    every = {"AAA": [1, 2, 3, 4], "BBB": [1, 2, 3, 4], "CCC": [1, 2, 3, 4]}
    thin = _window(7, {"AAA": [8], "BBB": [9]}, first=8)
    pending = Window(thin.week, thin.start, thin.end, thin.games, unscheduled=[date(2026, 12, 10)])
    readings = _readings((STAR, 40.0), (SECOND, 30.0), (BENCH, 10.0))

    outlook = build([_window(6, every), pending], [STAR, SECOND, BENCH], [], readings, {}, adds=3)

    assert outlook.usual == 8  # the final week alone
    week = outlook.weeks[1]
    assert (week.provisional, week.short, week.light, week.fix) == (True, False, [], "")
    assert outlook.weeks[0].provisional is False
