"""Tests for what a basketball week asks of the manager: `nba/actions.py`."""

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.actions import STREAMS, build, droppable, held, starts, streams
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer


def _player(name: str, slot: str = "", position: str = "PF", status: str = "") -> YahooPlayer:
    return make_player(name, position=position, key=name, selected_position=slot, status=status)


def _read(player: YahooPlayer, per_game: float, games: int) -> Reading:
    return Reading(player=player, line={}, per_game=per_game, games=games)


def _readings(*pairs: tuple[YahooPlayer, float, int]) -> dict[str, Reading]:
    return {player.player_key: _read(player, per, games) for player, per, games in pairs}


def _figures(item_players: list, label: str) -> list[str]:
    return [next(f.value for f in p.figures if f.label == label) for p in item_players]


# ── starts ──────────────────────────────────────────────────────────


def test_a_bench_player_with_more_games_starts_over_the_starter_he_can_replace() -> None:
    starter, bench = _player("Starter", "PF"), _player("Bench", "BN")
    readings = _readings((starter, 30.0, 1), (bench, 25.0, 3))

    [item] = starts([starter, bench], readings, by_points=True)

    assert (item.player_id, item.replaces, item.kind) == ("Bench", "Starter", "lineup")
    assert [(p.side, p.held) for p in item.players] == [("in", "bench"), ("out", "starter")]
    assert _figures(item.players, "G left") == ["3", "1"]
    assert _figures(item.players, "Week") == ["75.0", "30.0"]


def test_a_bench_player_yahoo_will_not_slot_there_is_no_start() -> None:
    starter, bench = _player("Starter", "C", position="C"), _player("Bench", "BN", position="PG")

    assert starts([starter, bench], _readings((starter, 10.0, 1), (bench, 30.0, 4)), by_points=True) == []


def test_a_guard_fills_a_guard_slot_and_anybody_a_utility_one() -> None:
    guard_slot, util = _player("Two Guard", "G", position="SG"), _player("Utility", "Util", position="C")
    bench = _player("Bench", "BN", position="PG")
    readings = _readings((guard_slot, 10.0, 1), (util, 12.0, 1), (bench, 30.0, 4))

    [item] = starts([guard_slot, util, bench], readings, by_points=True)

    assert item.replaces == "Two Guard"  # the weakest he could replace


def test_a_gain_inside_the_margin_is_no_start() -> None:
    starter, bench = _player("Starter", "PF"), _player("Bench", "BN")

    assert starts([starter, bench], _readings((starter, 30.0, 2), (bench, 33.0, 2)), by_points=True) == []


def test_each_starter_is_replaced_once_by_the_biggest_gain() -> None:
    starter = _player("Starter", "PF")
    better, best = _player("Better", "BN"), _player("Best", "BN")
    readings = _readings((starter, 10.0, 1), (better, 20.0, 2), (best, 30.0, 2))

    [item] = starts([starter, better, best], readings, by_points=True)

    assert item.player_id == "Best"


def test_a_starter_who_cannot_play_this_week_is_beaten_by_anyone_who_can() -> None:
    starter, bench = _player("Hurt", "PF", status="O"), _player("Bench", "BN")

    [item] = starts([starter, bench], _readings((starter, 40.0, 0), (bench, 5.0, 1)), by_points=False)

    assert item.replaces == "Hurt"
    assert "value" in item.reason


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


def test_one_more_game_never_costs_a_much_better_player() -> None:
    """A stream is one week; the player dropped is gone for good."""
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 13.0, 4))

    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []


def test_the_week_lists_il_moves_then_starts_then_streams() -> None:
    starter, bench = _player("Starter", "PF"), _player("Bench", "BN")
    back = _player("Back", "IL")
    pickup = _player("Pickup")
    filler = _player("Filler", "BN")
    readings = _readings((starter, 30.0, 1), (bench, 25.0, 3), (back, 20.0, 2), (pickup, 25.0, 4), (filler, 5.0, 1))

    items = build([starter, bench, back, filler], [pickup], readings, adds_left=1, by_points=True)

    assert [item.key.split(":")[0] for item in items] == ["il", "start", "stream"]
    assert items[-1].drop == "Filler"


def test_where_a_player_stands_follows_his_slot() -> None:
    assert [held(_player("A", slot)) for slot in ("PG", "BN", "IL+", "")] == [
        "starter",
        "bench",
        "reserve",
        "free agent",
    ]
