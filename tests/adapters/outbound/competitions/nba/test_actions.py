"""Tests for what a basketball week asks of the manager: `nba/actions.py`."""

from dataclasses import replace
from datetime import date

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.actions import (
    PROVISIONAL,
    STREAMS,
    build,
    droppable,
    fit,
    held,
    starts,
    streams,
)
from thefrontoffice.adapters.outbound.competitions.nba.week import Today
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory, YahooLine, YahooPlayer


def _player(name: str, slot: str = "", position: str = "PF", status: str = "", team: str = "LAL") -> YahooPlayer:
    return make_player(name, position=position, team=team, key=name, selected_position=slot, status=status)


def _read(player: YahooPlayer, per_game: float, games: int) -> Reading:
    return Reading(player=player, line={}, per_game=per_game, games=games)


def _readings(*pairs: tuple[YahooPlayer, float, int]) -> dict[str, Reading]:
    return {player.player_key: _read(player, per, games) for player, per, games in pairs}


def _figures(item_players: list, label: str) -> list[str]:
    return [next(f.value for f in p.figures if f.label == label) for p in item_players]


# ── starts ──────────────────────────────────────────────────────────

DAY = date(2026, 11, 20)


def _slate(*games: tuple[str, str, str]) -> Today:
    """Today's games, each as home, away and Sleeper's status."""
    return Today(DAY, [ScheduledGame(week=0, date=DAY.isoformat(), home=h, away=a, status=st) for h, a, st in games])


TONIGHT = _slate(("LAL", "BOS", "pre_game"))
"""The Lakers and Celtics play tonight; every other club rests."""


def test_a_starter_with_no_game_today_gives_way_to_a_bench_player_with_one() -> None:
    """A lineup is set daily: however good his week, a starter who rests today scores nothing today."""
    starter, bench = _player("Rests", "PF", team="DEN"), _player("Plays", "BN", team="LAL")
    readings = _readings((starter, 30.0, 3), (bench, 10.0, 1))

    [item] = starts([starter, bench], readings, by_points=True, today=TONIGHT)

    assert (item.player_id, item.replaces, item.kind, item.urgency) == ("Plays", "Rests", "lineup", "now")
    assert [(p.side, p.held) for p in item.players] == [("in", "bench"), ("out", "starter")]
    assert "vs BOS" in item.reason
    assert item.key == f"start:{DAY.isoformat()}:Plays:Rests"


def test_a_bench_player_with_no_game_today_is_never_started() -> None:
    """Twice the player and three games to come still scores nothing tonight."""
    starter, bench = _player("Plays", "Util", team="LAL"), _player("Rests", "BN", team="DEN")

    assert starts([starter, bench], _readings((starter, 5.0, 1), (bench, 15.0, 3)), True, TONIGHT) == []


def test_when_both_play_the_better_a_game_starts_by_the_margin() -> None:
    starter, bench = _player("Starter", "PF", team="LAL"), _player("Bench", "BN", team="BOS")

    [item] = starts([starter, bench], _readings((starter, 10.0, 3), (bench, 15.0, 1)), True, TONIGHT)
    assert item.player_id == "Bench"
    assert starts([starter, bench], _readings((starter, 10.0, 1), (bench, 11.0, 3)), True, TONIGHT) == []


def test_a_bench_player_yahoo_will_not_slot_there_is_no_start() -> None:
    starter = _player("Starter", "C", position="C", team="DEN")
    bench = _player("Bench", "BN", position="PG")

    assert starts([starter, bench], _readings((starter, 10.0, 1), (bench, 30.0, 4)), True, TONIGHT) == []


def test_a_guard_fills_a_guard_slot_and_anybody_a_utility_one() -> None:
    guard_slot, util = _player("Two Guard", "G", position="SG"), _player("Utility", "Util", position="C")
    bench = _player("Bench", "BN", position="PG", team="BOS")
    readings = _readings((guard_slot, 10.0, 1), (util, 12.0, 1), (bench, 30.0, 4))

    [item] = starts([guard_slot, util, bench], readings, True, TONIGHT)

    assert item.replaces == "Two Guard"  # the weakest he could replace


def test_a_starter_resting_is_replaced_before_a_weaker_one_playing() -> None:
    playing, resting = _player("Weak", "PF"), _player("Rests", "SF", team="DEN")
    bench = _player("Bench", "BN", position="PF,SF", team="BOS")
    readings = _readings((playing, 5.0, 1), (resting, 20.0, 1), (bench, 15.0, 1))

    [item] = starts([playing, resting, bench], readings, True, TONIGHT)

    assert item.replaces == "Rests"


def test_a_starter_ruled_out_of_tonights_game_is_replaced() -> None:
    starter, bench = _player("Hurt", "PF", status="O"), _player("Bench", "BN", team="BOS")

    [item] = starts([starter, bench], _readings((starter, 40.0, 0), (bench, 5.0, 1)), False, TONIGHT)

    assert item.replaces == "Hurt"
    assert "ruled out" in item.reason


def test_a_bench_player_ruled_out_is_never_started() -> None:
    starter, bench = _player("Rests", "PF", team="DEN"), _player("Hurt", "BN", status="O")

    assert starts([starter, bench], _readings((starter, 5.0, 1), (bench, 30.0, 1)), True, TONIGHT) == []


def test_nobody_moves_once_his_game_has_tipped_off() -> None:
    """Yahoo locks a player at his game's start, in the lineup or out of it."""
    under_way = _slate(("LAL", "BOS", "in_game"), ("DEN", "MIA", "pre_game"))
    locked, bench = _player("Locked", "PF"), _player("Bench", "BN", team="DEN")
    assert starts([locked, bench], _readings((locked, 5.0, 1), (bench, 30.0, 1)), True, under_way) == []

    resting, too_late = _player("Rests", "PF", team="NYK"), _player("Too Late", "BN", team="BOS")
    assert starts([resting, too_late], _readings((resting, 5.0, 1), (too_late, 30.0, 1)), True, under_way) == []


def test_without_todays_games_there_is_no_start() -> None:
    """The schedule would not load, or today is outside the week: a weekly guess can start a player who rests."""
    starter, bench = _player("Starter", "PF"), _player("Bench", "BN")

    assert starts([starter, bench], _readings((starter, 5.0, 1), (bench, 30.0, 3)), True, None) == []


def test_each_starter_is_replaced_once_by_the_biggest_gain() -> None:
    starter = _player("Starter", "PF", team="DEN")
    better, best = _player("Better", "BN"), _player("Best", "BN", team="BOS")
    readings = _readings((starter, 10.0, 1), (better, 20.0, 2), (best, 30.0, 2))

    [item] = starts([starter, better, best], readings, True, TONIGHT)

    assert item.player_id == "Best"


# ── streams and drops ───────────────────────────────────────────────


def _team() -> tuple[list[YahooPlayer], dict[str, Reading]]:
    """Four active players and one on IL: the better half is never offered."""
    stars = [_player("Star", "PF"), _player("Second", "C")]
    weak = [_player("Weak", "BN"), _player("Weaker", "BN")]
    hurt = _player("Hurt", "IL", status="O")
    readings = _readings(
        (stars[0], 50.0, 1), (stars[1], 40.0, 1), (weak[0], 20.0, 2), (weak[1], 18.0, 2), (hurt, 5.0, 0)
    )
    return [*stars, *weak, hurt], readings


def test_the_drop_is_the_weakest_this_week_outside_the_better_half_and_never_on_il() -> None:
    roster, readings = _team()

    assert [r.player.name for r in droppable(roster, readings, set())] == ["Weaker", "Weak"]


def test_a_player_another_item_moves_is_not_offered_as_a_drop() -> None:
    roster, readings = _team()

    assert [r.player.name for r in droppable(roster, readings, {"Weaker"})] == ["Weak"]


def test_a_free_agent_with_more_this_week_streams_in_for_the_weakest_drop() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 20.0, 4))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert (item.kind, item.player_id, item.drop) == ("waiver", "Pickup", "Weaker")
    assert [(p.side, p.held) for p in item.players] == [("in", "free agent"), ("out", "bench")]


def test_a_category_drop_says_what_drags_him() -> None:
    """'Weakest you can drop' alone is a verdict; the categories behind it make it a reason."""
    roster, readings = _team()
    readings["Weaker"] = replace(
        readings["Weaker"],
        weak=(StatCategory("5", "FG%"), StatCategory("19", "TO", fewer_wins=True)),
        average=YahooLine(stats={"5": ".380", "19": "2.9"}),
    )
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 20.0, 4))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=False, named=set())

    assert "(FG% .380 · 2.9 TO)" in item.reason


def test_no_adds_left_is_nothing_to_stream() -> None:
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 20.0, 4))

    assert streams(roster, [pickup], readings, adds_left=0, by_points=True, named=set()) == []


def test_streams_stop_at_the_adds_left() -> None:
    roster, readings = _team()
    wire = [_player(f"Pickup {i}") for i in range(STREAMS)]
    readings |= _readings(*((p, 20.0, 4) for p in wire))

    assert len(streams(roster, wire, readings, adds_left=1, by_points=True, named=set())) == 1


def test_a_free_agent_ruled_out_is_never_streamed() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", status="O")
    readings |= _readings((pickup, 30.0, 3))

    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []


# ── how a free agent fits ───────────────────────────────────────────


def test_a_free_agent_fits_over_the_weakest_drop_he_clears_by_the_margin() -> None:
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 20.0, 4))

    said = fit(readings["Pickup"], roster, readings, by_points=True)

    assert "Weaker" in said
    assert "+44.0 fpts" in said  # 80 this week against 36
    assert "4G vs 2G" in said


def test_a_free_agent_inside_the_margin_fits_over_nobody() -> None:
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 19.0, 2))

    assert fit(readings["Pickup"], roster, readings, by_points=False) == ""


def test_one_more_game_never_costs_a_much_better_player() -> None:
    """A stream is one week; the player dropped is gone for good."""
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 13.0, 4))

    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []


def test_a_stream_never_gives_up_a_better_player_a_game_for_more_games() -> None:
    """Twice the games this week does not make a lesser player worth dropping a better one for."""
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 17.0, 4))  # 68 this week against Weaker's 36, but 17 a game against 18

    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []


def test_the_week_lists_il_moves_then_starts_then_streams() -> None:
    starter, bench = _player("Starter", "PF", team="DEN"), _player("Bench", "BN")
    back = _player("Back", "IL")
    pickup = _player("Pickup")
    filler = _player("Filler", "BN")
    readings = _readings((starter, 30.0, 1), (bench, 25.0, 3), (back, 20.0, 2), (pickup, 25.0, 4), (filler, 5.0, 1))

    items = build([starter, bench, back, filler], [pickup], readings, adds_left=1, by_points=True, today=TONIGHT)

    assert [item.key.split(":")[0] for item in items] == ["il", "start", "stream"]
    assert items[-1].drop == "Filler"


def test_where_a_player_stands_follows_his_slot() -> None:
    assert [held(_player("A", slot)) for slot in ("PG", "BN", "IL+", "")] == [
        "starter",
        "bench",
        "reserve",
        "free agent",
    ]


def test_a_stream_weighed_on_a_schedule_not_final_says_it_is_provisional() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= {"Pickup": replace(_read(pickup, 20.0, 4), provisional=True)}

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert item.reason.endswith(PROVISIONAL)
    assert _figures(item.players, "G left")[0] == "4+"
