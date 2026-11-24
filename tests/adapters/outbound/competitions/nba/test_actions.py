"""Tests for what a basketball week asks of the manager: `nba/actions.py`."""

from dataclasses import replace
from datetime import date

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nba.actions import (
    PROVISIONAL,
    STREAM_GAMES,
    STREAMS,
    Plan,
    Weigh,
    acquire,
    build,
    droppable,
    fit,
    held,
    reserving,
    starts,
    streams,
)
from thefrontoffice.adapters.outbound.competitions.nba.form import Role
from thefrontoffice.adapters.outbound.competitions.nba.lineup import Week
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, POINTS, chance
from thefrontoffice.adapters.outbound.competitions.nba.teammates import (
    RETURN_CUT,
    Absent,
    Condition,
    Propped,
    Regular,
    Returning,
    Split,
)
from thefrontoffice.adapters.outbound.competitions.nba.week import Today
from thefrontoffice.adapters.outbound.competitions.nba.worth import (
    UNNEEDED,
    Reading,
    Scale,
    Targeting,
    category_value,
    scales,
)
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
    assert "Claim" not in item.title
    assert "waivers" not in item.reason


def test_an_untouchable_player_is_never_the_drop_for_a_stream() -> None:
    """The weakest is the manager's to keep: the next weakest makes way."""
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 20.0, 4))
    plan = Plan(untouchable=frozenset({"Weaker"}))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set(), plan=plan)

    assert item.drop == "Weak"


def test_a_free_agent_fits_over_nobody_untouchable() -> None:
    roster, readings = _team()
    pickup = _player("Pickup")
    readings |= _readings((pickup, 20.0, 4))

    said = fit(readings["Pickup"], roster, readings, by_points=True, untouchable={"Weaker"})

    assert "Weaker" not in said


def test_a_player_on_waivers_streams_in_as_a_claim_on_the_games_after_he_clears_them() -> None:
    """His reading already counts only those games; the item says so, and when he clears."""
    roster, readings = _team()
    pickup = replace(_player("Pickup", position="SF"), waiver_date=date(2026, 11, 25))
    readings |= _readings((pickup, 25.0, 3))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert (item.player_id, item.drop) == ("Pickup", "Weaker")
    assert [(p.side, p.held) for p in item.players] == [("in", "waivers"), ("out", "bench")]
    assert item.title.startswith("Claim Pickup")
    assert "25 Nov" in item.title
    assert "3 games" in item.title
    assert "Wed 25 Nov" in item.reason
    assert _figures(item.players, "G left") == ["3", "2"]


def test_a_claim_is_weighed_on_the_games_after_he_clears_so_too_few_stream_nothing() -> None:
    roster, readings = _team()
    pickup = replace(_player("Pickup", position="SF"), waiver_date=date(2026, 11, 25))
    readings |= _readings((pickup, 20.0, 1))  # four games for his club, one after he clears

    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []


def test_a_pickup_is_named_by_how_he_is_had_with_what_the_caller_gives() -> None:
    waiting = replace(_player("Lopez"), waiver_date=date(2026, 11, 25))

    assert acquire(_player("Dunn")) == "Pick up Dunn"
    assert acquire(_player("Dunn"), 4, "PG", "LAC") == "Pick up Dunn (PG, LAC, 4 games)"
    assert acquire(waiting, 2, "C", "LAC") == "Claim Lopez (C, LAC, clears 25 Nov, 2 games)"


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


def test_a_marginal_stream_one_game_over_a_player_barely_weaker_is_not_suggested() -> None:
    """Turner for Buzelis: 19 a game against 18, three games against two. +21 clears the margin on the week,
    but is barely more than one of Weaker's games, short of `STREAM_GAMES`: not worth one of the week's adds."""
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 19.0, 3))

    assert STREAM_GAMES * 18.0 > 19.0 * 3 - 18.0 * 2
    assert streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set()) == []
    assert fit(readings["Pickup"], roster, readings, by_points=True) == ""


def test_a_clearly_better_stream_is_still_suggested() -> None:
    """The same player with a fourth game adds +40, over two of Weaker's games: a stream worth an add."""
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 19.0, 4))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert (item.pickup, item.drop) == ("streamer", "Weaker")
    assert "+40.0" in item.reason


def test_a_stream_lets_go_the_weakest_player_a_game_before_the_one_weakest_this_week() -> None:
    """Weak plays once, so his week is the smaller; Weaker is the player you would miss least for good."""
    roster, readings = _team()
    readings["Weak"] = replace(readings["Weak"], games=1)
    readings["Weaker"] = replace(readings["Weaker"], per_game=12.0, games=3)
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 22.0, 4))

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert item.drop == "Weaker"


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
    assert held(replace(_player("A"), waiver_date=date(2026, 11, 25))) == "waivers"


def test_a_stream_weighed_on_a_schedule_not_final_says_it_is_provisional() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= {"Pickup": replace(_read(pickup, 20.0, 4), provisional=True)}

    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())

    assert item.reason.endswith(PROVISIONAL)
    assert _figures(item.players, "G left")[0] == "4+"


# ── streamers and keepers ───────────────────────────────────────────


def test_a_player_whose_minutes_are_growing_is_never_the_drop() -> None:
    """His value a game still reads the role he had; the one he is growing into is the one you would lose."""
    roster, readings = _team()
    readings["Weaker"] = replace(readings["Weaker"], rising=True)
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 21.0, 4))

    assert [r.player.name for r in droppable(roster, readings, set())] == ["Weak"]
    [item] = streams(roster, [pickup], readings, adds_left=2, by_points=True, named=set())
    assert item.drop == "Weak"


def test_a_pickup_no_better_a_game_is_a_streamer_and_one_clearly_better_a_keeper() -> None:
    roster, readings = _team()
    streamer, keeper = _player("Streamer", position="SF"), _player("Keeper", position="SF")
    readings |= _readings((streamer, 21.0, 4), (keeper, 30.0, 3))

    items = streams(roster, [streamer, keeper], readings, adds_left=2, by_points=True, named=set())

    assert [(item.player_id, item.pickup, item.drop) for item in items] == [
        ("Streamer", "streamer", "Weak"),
        ("Keeper", "keeper", "Weaker"),  # the weakest a game, whatever his week
    ]


def test_a_role_just_grown_streams_until_it_holds() -> None:
    """Minutes up by ten over his last five: as often a teammate's absence as a promotion."""
    roster, readings = _team()
    riser = _player("Riser", position="SF")
    readings |= {"Riser": replace(_read(riser, 30.0, 3), role=Role(games=5, minutes=30.0, window=20.0))}

    [item] = streams(roster, [riser], readings, adds_left=2, by_points=True, named=set())

    assert item.pickup == "streamer"


def test_a_keeper_beyond_the_adds_left_is_named_as_the_alternative_on_a_drop_of_its_own() -> None:
    roster, readings = _team()
    wire = [_player(f"Keeper {i}", position="SF") for i in range(3)]
    readings |= _readings(*((p, 30.0 - i, 3) for i, p in enumerate(wire)))

    planned, alternative = streams(roster, wire, readings, adds_left=1, by_points=True, named=set())

    assert [(item.player_id, item.drop, item.pickup) for item in (planned, alternative)] == [
        ("Keeper 0", "Weaker", "keeper"),
        ("Keeper 1", "Weak", "keeper"),
    ]
    assert "Keeper 0" in alternative.reason


def test_with_one_add_left_the_week_comes_before_a_keeper_who_adds_less_to_it() -> None:
    roster, readings = _team()
    streamer, keeper = _player("Streamer", position="SF"), _player("Keeper", position="SF")
    readings |= _readings((streamer, 21.0, 4), (keeper, 30.0, 1))

    items = streams(roster, [streamer, keeper], readings, adds_left=1, by_points=True, named=set())

    assert [(item.player_id, item.pickup) for item in items] == [("Streamer", "streamer")]


MON, TUE, WED = (date(2026, 11, day) for day in (23, 24, 25))
THANKSGIVING = date(2026, 11, 26)


def _week(*nights: tuple[date, str, str], lineup: tuple[str, ...] = ("PF", "SF", "Util")) -> Week:
    games = [ScheduledGame(week=0, date=day.isoformat(), home=h, away=a) for day, h, a in nights]
    return Week(games=games, slots=lineup, today=MON, end=date(2026, 11, 29))


DETROIT = _week((MON, "DET", "BOS"), (TUE, "DET", "NYK"), (WED, "DET", "MIA"), (date(2026, 11, 28), "DET", "PHX"))
"""The Pistons play Monday to Wednesday and Saturday; nobody plays on Thanksgiving."""


def _duren(back: date) -> Returning:
    regular = Regular(player_id="d1", name="Jalen Duren", team="DET", position="C")
    return Returning(Absent(regular, Condition(status="O", returns=back)), without=12, alongside=1)


def test_a_pickup_counts_the_games_after_a_teammates_return_at_a_cut() -> None:
    """Reed's role is Duren's absence: Monday counts in full, the three from Duren's return on Tuesday at a cut."""
    roster, readings = _team()
    reed = _player("Reed", position="PF,C", team="DET")
    readings |= _readings((reed, 10.0, 4))
    weak = readings["Weak"]

    alone, _ = Weigh(roster, readings, Plan(week=DETROIT)).gained(readings["Reed"], weak)
    behind, nights = Weigh(roster, readings, Plan(week=DETROIT, returning={"Reed": _duren(TUE)})).gained(
        readings["Reed"], weak
    )

    assert nights == 4
    assert alone == 40.0
    assert behind == 10.0 + 3 * 10.0 * RETURN_CUT


def _reaves(back: date, cut: float) -> Propped:
    """Thybulle's split without Reaves, five games each side: enough to read, so no `Returning` flag."""
    regular = Regular(player_id="a1", name="Austin Reaves", team="DET", position="SG")
    absent = Absent(regular, Condition(status="O", returns=back))
    split = Split(teammates=(absent,), without={}, games=5, alongside={}, alongside_games=12)
    return Propped(split, back, cut)


def test_a_pickup_propped_up_by_a_teammate_due_back_is_a_streamer_with_his_games_after_at_the_splits_cut() -> None:
    """Clearly better a game than any drop reads as a keeper; but his split without Reaves, back Wednesday, is
    his role."""
    roster, readings = _team()
    thybulle = _player("Thybulle", position="SG,SF", team="DET")
    readings |= _readings((thybulle, 30.0, 4))
    plan = Plan(week=DETROIT, returning={"Thybulle": _reaves(WED, 0.75)})

    [item] = streams(roster, [thybulle], readings, adds_left=2, by_points=True, named=set(), plan=plan)
    gained, _ = Weigh(roster, readings, plan).gained(readings["Thybulle"], readings["Weak"])

    assert item.pickup == "streamer"
    assert "Reaves" in item.reason and "75%" in item.reason
    assert gained == 30.0 * 2 + 30.0 * 2 * 0.75  # Monday and Tuesday in full; Wednesday and Saturday at the cut
    assert streams(roster, [thybulle], readings, 2, True, set(), plan=Plan(week=DETROIT))[0].pickup == "keeper"


def test_a_pickup_whose_role_leans_on_a_teammate_due_back_is_never_a_keeper() -> None:
    roster, readings = _team()
    reed = _player("Reed", position="PF,C", team="DET")
    readings |= _readings((reed, 30.0, 4))
    plan = Plan(week=DETROIT, returning={"Reed": _duren(TUE)})

    [item] = streams(roster, [reed], readings, adds_left=2, by_points=True, named=set(), plan=plan)

    assert item.pickup == "streamer"
    assert "Duren" in item.reason


def test_only_the_nights_a_slot_is_open_count_toward_a_pickups_week() -> None:
    """A lone forward slot, taken by a Celtic on Monday: a forward from Detroit fills it the other three nights."""
    celtic = _player("Celtic", "SF", position="SF", team="BOS")
    spare = _player("Spare", "BN", position="C", team="LAL")
    pickup = _player("Pickup", position="SF", team="DET")
    readings = _readings((celtic, 30.0, 1), (spare, 1.0, 0), (pickup, 10.0, 4))

    gained, nights = Weigh([celtic, spare], readings, Plan(week=replace(DETROIT, slots=("SF",)))).gained(
        readings["Pickup"], readings["Spare"]
    )

    assert (gained, nights) == (30.0, 3)


def test_a_keeper_out_a_few_days_is_added_on_the_day_nobody_plays() -> None:
    roster, readings = _team()
    robinson = _player("Robinson", position="SG,SF", team="DET", status="O")
    readings |= {"Robinson": replace(_read(robinson, 30.0, 1), back=date(2026, 11, 27))}

    [item] = streams(roster, [robinson], readings, adds_left=2, by_points=True, named=set(), plan=Plan(week=DETROIT))

    assert item.pickup == "keeper"
    assert item.when == weekday_day_month(THANKSGIVING)
    readings["Robinson"] = replace(readings["Robinson"], back=WED)  # every day before then has games
    [sooner] = streams(roster, [robinson], readings, 2, True, set(), plan=Plan(week=DETROIT))
    assert (sooner.pickup, sooner.when) == ("keeper", weekday_day_month(MON))  # added today


def test_a_keeper_out_beyond_the_week_or_with_no_week_to_place_his_return_is_not_offered() -> None:
    roster, readings = _team()
    hurt = _player("Hurt", position="SF", team="DET", status="O")
    readings |= {"Hurt": replace(_read(hurt, 30.0, 0), back=date(2026, 12, 20))}

    assert streams(roster, [hurt], readings, 2, True, set(), plan=Plan(week=DETROIT)) == []
    readings["Hurt"] = replace(readings["Hurt"], back=WED)
    assert streams(roster, [hurt], readings, 2, True, set()) == []


# ── the week's adds, planned as a sequence ──────────────────────────

FRI, SAT, SUN = (date(2026, 11, day) for day in (27, 28, 29))
BRIDGED = _week(
    *((day, "CHA", "ORL") for day in (MON, TUE, WED)),
    (SAT, "DET", "ORL"),
    *((day, "PHX", "UTA") for day in (MON, TUE, WED, FRI, SAT, SUN)),
)
"""Charlotte plays Monday to Wednesday, Detroit Saturday, Phoenix six nights; nobody plays on Thanksgiving."""


def _waiting(*wire: tuple[str, str, float]) -> tuple[list[YahooPlayer], dict[str, Reading], list[YahooPlayer]]:
    """`_team` with Weak a Hornet, Robinson out until Friday on the wire, and `wire` as (name, club, value a game)."""
    roster, readings = _team()
    roster = [replace(p, team="CHA") if p.name == "Weak" else p for p in roster]
    readings["Weak"] = replace(readings["Weak"], player=roster[2])
    robinson = _player("Robinson", position="SG,SF", team="DET", status="O")
    others = [_player(name, position="SF", team=club) for name, club, _ in wire]
    readings |= {"Robinson": replace(_read(robinson, 30.0, 1), back=date(2026, 11, 27))}
    readings |= _readings(*((p, value, 0) for p, (_, _, value) in zip(others, wire, strict=True)))
    return roster, readings, [robinson, *others]


def test_a_keeper_out_until_mid_week_is_bridged_by_a_stream_let_go_for_him_on_the_day_nobody_plays() -> None:
    """Weaker sits idle until Thanksgiving: a Hornet holds his spot three nights, then makes way for Robinson."""
    roster, readings, wire = _waiting(("Hornet", "CHA", 21.0))

    [item] = streams(roster, wire, readings, adds_left=2, by_points=True, named=set(), plan=Plan(week=BRIDGED))

    assert (item.kind, item.urgency, item.player_id, item.drop, item.pickup) == (
        "waiver",
        "now",
        "Hornet",
        "Weaker",
        "streamer",
    )
    assert [(p.side, p.name) for p in item.players] == [("in", "Hornet"), ("out", "Weaker"), ("in", "Robinson")]
    assert weekday_day_month(THANKSGIVING) in item.title and "Robinson" in item.title
    assert "+63.0" in item.reason  # three nights of 21 over a drop with none


def test_with_one_add_left_no_sequence_is_planned() -> None:
    roster, readings, wire = _waiting(("Hornet", "CHA", 21.0))

    items = streams(roster, wire, readings, adds_left=1, by_points=True, named=set(), plan=Plan(week=BRIDGED))

    assert [(item.player_id, item.pickup) for item in items] == [("Hornet", "streamer")]
    assert all(len(item.players) == 2 for item in items)


def test_a_stream_worth_more_for_the_week_than_the_bridge_keeps_the_single_suggestions() -> None:
    """Six nights of a Sun beat three of him before Thanksgiving: stream him for the week, add Robinson then."""
    roster, readings, wire = _waiting(("Sun", "PHX", 21.5))

    items = streams(roster, wire, readings, adds_left=2, by_points=True, named=set(), plan=Plan(week=BRIDGED))

    assert [(item.player_id, item.drop, item.pickup) for item in items] == [
        ("Sun", "Weak", "streamer"),
        ("Robinson", "Weaker", "keeper"),
    ]


def test_a_third_add_streams_beside_the_planned_sequence() -> None:
    roster, readings, wire = _waiting(("Sun", "PHX", 21.5), ("Hornet", "CHA", 21.0))

    items = streams(roster, wire, readings, adds_left=3, by_points=True, named=set(), plan=Plan(week=BRIDGED))

    assert [(item.player_id, item.drop, len(item.players)) for item in items] == [
        ("Sun", "Weak", 2),
        ("Hornet", "Weaker", 3),
    ]


def test_a_claim_or_a_player_ruled_out_never_bridges_the_wait() -> None:
    """Waivers or an injury eat the few nights a bridge is there for: Robinson is added alone on Thanksgiving."""
    roster, readings, wire = _waiting(("Hornet", "CHA", 21.0))
    claimed = replace(wire[1], waiver_date=MON)
    hurt = replace(wire[1], status="O")

    for hornet in (claimed, hurt):
        readings["Hornet"] = replace(readings["Hornet"], player=hornet)
        items = streams(roster, [wire[0], hornet], readings, 2, True, set(), plan=Plan(week=BRIDGED))

        assert all(not item.key.startswith("plan:") for item in items)
        assert ("Robinson", "keeper", weekday_day_month(THANKSGIVING)) in [
            (item.player_id, item.pickup, item.when) for item in items
        ]


def test_a_stream_is_urged_now_when_the_opponent_can_start_more_games() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 21.0, 4))

    [behind] = streams(roster, [pickup], readings, 2, True, set(), plan=Plan(volume=(39, 44)))
    [ahead] = streams(roster, [pickup], readings, 2, True, set(), plan=Plan(volume=(44, 39)))

    assert (behind.urgency, ahead.urgency) == ("now", "soon")
    assert "39" in behind.reason and "44" in behind.reason


def test_a_lead_in_games_the_opponents_streams_could_take_back_still_urges_a_stream() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 21.0, 4))

    [catchable] = streams(roster, [pickup], readings, 2, True, set(), plan=Plan(volume=(41, 39), streams=3))
    [safe] = streams(roster, [pickup], readings, 2, True, set(), plan=Plan(volume=(44, 39), streams=3))

    assert (catchable.urgency, safe.urgency) == ("now", "soon")
    assert "+3" in catchable.reason


# ── this week's categories, weighed by how winnable each is ─────────

CATS = (StatCategory(POINTS.yahoo_stat, "PTS"), StatCategory(BLOCKS.yahoo_stat, "BLK"))
LINES = [{POINTS.label: 10.0, BLOCKS.label: 0.0}, {POINTS.label: 30.0, BLOCKS.label: 2.0}]
SCORER = {POINTS.label: 20.0, BLOCKS.label: 0.0}


def _scorer_against(blocker: dict[str, float]) -> tuple[list[YahooPlayer], dict[str, Reading], YahooPlayer]:
    """A scorer to drop and a blocker on the wire, two games each, read on the season's scale."""
    stars = [_player("Star", "PF"), _player("Second", "C")]
    scorer, wire = _player("Scorer", "BN"), _player("Blocker", position="SF")
    value = category_value(CATS, LINES)
    readings = _readings((stars[0], 50.0, 2), (stars[1], 40.0, 2))
    readings |= {
        p.player_key: Reading(player=p, line=figures, per_game=value(figures), games=2)
        for p, figures in ((scorer, SCORER), (wire, blocker))
    }
    return [*stars, scorer], readings, wire


def _targeting(**chances: float) -> Plan:
    return Plan(targeting=Targeting.of(scales(CATS, LINES), chances))


EVEN_BLOCKER = {POINTS.label: 0.0, BLOCKS.label: 2.0}
"""As much a game as the scorer on the season's scale: two blocks against twenty points."""


def test_a_pickup_is_weighed_on_the_categories_still_in_play_this_week() -> None:
    """Points all but won, blocks even: the blocker streams over the scorer, and names what he targets."""
    roster, readings, blocker = _scorer_against(EVEN_BLOCKER)

    assert streams(roster, [blocker], readings, 2, False, set()) == []
    [item] = streams(roster, [blocker], readings, 2, False, set(), plan=_targeting(PTS=0.98, BLK=0.5))

    assert (item.player_id, item.drop, item.pickup) == ("Blocker", "Scorer", "streamer")
    assert "BLK" in item.reason and "PTS" not in item.reason


def test_a_category_all_but_settled_never_drives_a_pickup() -> None:
    roster, readings, blocker = _scorer_against(EVEN_BLOCKER)

    assert streams(roster, [blocker], readings, 2, False, set(), plan=_targeting(PTS=0.5, BLK=0.99)) == []


def test_a_keeper_is_judged_on_his_value_a_game_whatever_this_weeks_opponent() -> None:
    """Twice the scorer a game for the season: a keeper even with blocks all but won this week."""
    roster, readings, blocker = _scorer_against({POINTS.label: 0.0, BLOCKS.label: 4.0})

    [item] = streams(roster, [blocker], readings, 2, False, set(), plan=_targeting(PTS=0.5, BLK=0.99))

    assert (item.player_id, item.pickup) == ("Blocker", "keeper")


# ── the week's adds as one plan: GM 3, week 6 ──────────────────────

THU = THANKSGIVING
GM3_SLOTS = ("PG", "SG", "G", "SF", "PF", "F", "C", "FC", "Util", "Util")
GM3_WEEK = Week(
    games=[
        ScheduledGame(week=0, date=day.isoformat(), home=home, away=away)
        for day, home, away in (
            (WED, "OKC", "MIN"),
            (WED, "DET", "CHI"),
            (WED, "MIL", "MEM"),
            (FRI, "OKC", "LAL"),
            (FRI, "DET", "MIN"),
            (FRI, "MIL", "MEM"),
            (SAT, "DET", "CHI"),
            (SUN, "MIL", "MIN"),
            (SUN, "NYK", "MEM"),
            (FRI, "NYK", "GSW"),
            (SAT, "PHX", "UTA"),
            (SUN, "PHX", "UTA"),
        )
    ],
    slots=GM3_SLOTS,
    today=TUE,
    end=SUN,
)
"""Tue 24 Nov to Sun 29 Nov, as the week stood: nobody plays on Thanksgiving."""


def _gm3() -> tuple[list[YahooPlayer], dict[str, Reading], list[YahooPlayer]]:
    """GM 3's roster and the top of the wire, each at his value a game as the league read it on Tue 24 Nov."""
    rows = [
        ("Shai Gilgeous-Alexander", "Util", "PG", "OKC", "", 16.1, 2),
        ("Austin Reaves", "SF", "PG,SG,SF", "LAL", "O", 15.3, 1),
        ("Cedric Coward", "F", "SG,SF", "MEM", "", 13.8, 3),
        ("Kyrie Irving", "PG", "PG,SG", "OKC", "", 13.2, 2),
        ("De'Andre Hunter", "Util", "SF,PF", "OKC", "", 12.2, 2),
        ("OG Anunoby", "BN", "SF,PF", "NYK", "O", 12.1, 2),
        ("Daniss Jenkins", "SG", "PG,SG", "DET", "", 11.5, 3),
        ("Ajay Mitchell", "G", "PG,SG", "OKC", "", 11.4, 2),
        ("Yaxel Lendeborg", "BN", "SF,PF", "GSW", "", 10.9, 1),
        ("Matas Buzelis", "PF", "SF,PF", "CHI", "", 9.2, 2),
        ("Aday Mara", "C", "C", "OKC", "Q", 9.0, 2),
        ("Coby White", "BN", "PG,SG", "CHI", "", 7.3, 2),
        ("Rudy Gobert", "FC", "C", "MIN", "", 5.5, 3),
        ("Jaren Jackson Jr.", "IL", "PF,C", "OKC", "O", 7.0, 0),
        ("Chet Holmgren", "IL", "PF,C", "OKC", "O", 15.1, 0),
    ]
    roster = [_player(name, slot, position, status, team) for name, slot, position, team, status, _, _ in rows]
    readings = _readings(*((p, row[5], row[6]) for p, row in zip(roster, rows, strict=True)))
    for grown in ("Daniss Jenkins", "Aday Mara", "Coby White"):  # minutes up in each of his last two
        readings[grown] = replace(readings[grown], rising=True)
    for back in ("Austin Reaves", "OG Anunoby"):
        readings[back] = replace(readings[back], back=FRI)
    spencer = replace(_player("Cam Spencer", position="PG,SG", team="PHX"), waiver_date=WED)
    robinson = _player("Duncan Robinson", position="SG,SF", team="DET", status="O")
    turner = _player("Myles Turner", position="C", team="MIL")
    readings |= {
        "Cam Spencer": replace(_read(spencer, 12.0, 3), role=Role(games=5, minutes=27.9, window=22.8)),
        "Duncan Robinson": replace(_read(robinson, 11.1, 2), back=FRI),
        "Myles Turner": _read(turner, 10.0, 3),
    }
    return roster, readings, [spencer, robinson, turner]


def _adds(items: list) -> list[tuple[str, str, str | None]]:
    return [(item.player_id, item.drop, item.pickup) for item in items if item.kind == "waiver"]


def test_a_week_all_but_lost_spends_its_adds_on_keepers_each_with_a_drop_of_its_own() -> None:
    """GM 3 at 1-8 and a 2% chance: no stream, two keepers, and Gobert let go once — Turner over him, Robinson,
    the better a game, over Buzelis, rather than Robinson alone over Gobert."""
    roster, readings, wire = _gm3()

    items = build(roster, wire, readings, adds_left=2, by_points=False, plan=Plan(week=GM3_WEEK, win=0.02))

    assert _adds(items) == [
        ("Myles Turner", "Rudy Gobert", "keeper"),
        ("Duncan Robinson", "Matas Buzelis", "keeper"),
    ]
    assert [item.when for item in items] == [weekday_day_month(TUE), weekday_day_month(THU)]
    assert {item.urgency for item in items} == {"soon"}
    assert all("2%" in item.reason for item in items)  # the pivot is stated, with the chance behind it


def test_a_week_in_play_streams_and_still_never_names_one_drop_twice_or_more_adds_than_left() -> None:
    roster, readings, wire = _gm3()

    items = build(roster, wire, readings, adds_left=2, by_points=False, plan=Plan(week=GM3_WEEK, win=0.4))
    adds = _adds(items)

    assert ("Cam Spencer", "streamer") in [(pickup, term) for pickup, _, term in adds]
    assert len({drop for _, drop, _ in adds}) == len(adds) <= 2
    assert len({pickup for pickup, _, _ in adds}) == len(adds)


def test_a_week_all_but_won_also_spends_its_adds_on_the_season() -> None:
    roster, readings, wire = _gm3()

    items = build(roster, wire, readings, adds_left=2, by_points=False, plan=Plan(week=GM3_WEEK, win=0.97))

    assert {term for _, _, term in _adds(items)} == {"keeper"}


def test_a_decided_week_names_a_keeper_past_its_adds_as_the_alternative_on_a_drop_of_its_own() -> None:
    roster, readings, wire = _gm3()
    reed = _player("Paul Reed", position="PF,C", team="DET")
    readings |= _readings((reed, 11.7, 3))

    planned, alternative = build(roster, [*wire, reed], readings, 1, False, plan=Plan(week=GM3_WEEK, win=0.02))

    assert (planned.player_id, planned.drop) == ("Paul Reed", "Rudy Gobert")
    assert (alternative.player_id, alternative.drop) == ("Duncan Robinson", "Matas Buzelis")
    assert "Paul Reed" in alternative.reason


def test_a_decided_week_with_no_keeper_clear_of_the_margin_adds_nobody() -> None:
    """A stream is the week's, and the week is settled."""
    roster, readings, wire = _gm3()
    readings = {key: r for key, r in readings.items() if key not in {"Duncan Robinson", "Myles Turner"}}

    assert streams(roster, wire, readings, 2, False, set(), plan=Plan(week=GM3_WEEK, win=0.02)) == []


# ── injured players, open spots, and who a drop lets go ────────────


def test_a_player_out_all_week_goes_to_an_open_il_slot_and_the_add_needs_no_drop() -> None:
    roster, readings = _team()
    out = _player("Out", "BN", status="O")
    roster.append(out)
    readings |= {"Out": replace(_read(out, 25.0, 0), back=date(2026, 12, 10))}
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 21.0, 4))

    move, add = build(roster, [pickup], readings, 2, True, plan=Plan(reserve=("IL",)))

    assert (move.kind, move.player_id, move.urgency) == ("lineup", "Out", "now")
    assert "IL" in move.title
    assert (add.player_id, add.drop) == ("Pickup", "")
    assert [p.side for p in add.players] == ["in"]


def test_a_move_to_il_plans_his_return_dropping_the_weakest_the_roster_will_hold() -> None:
    """Back 10 Dec: Weaker is the one to let go then — or the stream he made room for, where weaker still."""
    roster, readings = _team()
    out = _player("Out", "BN", status="O")
    roster.append(out)
    readings |= {"Out": replace(_read(out, 25.0, 0), back=date(2026, 12, 10))}
    keeper, stream = _player("Keeper", position="SF"), _player("Stream", position="SF")

    move, _ = build(roster, [keeper], readings | _readings((keeper, 21.0, 4)), 2, True, plan=Plan(reserve=("IL",)))
    streamed, _ = build(roster, [stream], readings | _readings((stream, 15.0, 4)), 2, True, plan=Plan(reserve=("IL",)))

    assert "Weaker" in move.reason and "Weak " not in move.reason
    assert "Stream" in streamed.reason and "Weaker" not in streamed.reason
    assert move.drop == ""  # nobody goes now: the drop is for the day he is back


def test_a_move_to_il_never_plans_an_untouchable_drop_at_his_return() -> None:
    out = _player("Out", "BN", status="O")
    star = _player("Star", "PF")
    readings = _readings((star, 50.0, 2)) | {"Out": _read(out, 25.0, 0)}

    [move] = build([star, out], [], readings, 2, True, plan=Plan(reserve=("IL",), untouchable=frozenset({"Star"})))

    assert move.player_id == "Out"
    assert "Star" not in move.reason


def test_a_keeper_only_just_clear_of_the_margin_says_it_is_close() -> None:
    """A fifth over Weaker's 18 is 21.6: 22 clears it by 2%, a coin flip; 30 does not need saying."""
    roster, readings = _team()
    close, clear = _player("Close", position="SF"), _player("Clear", position="SF")

    [near] = streams(roster, [close], readings | _readings((close, 22.0, 1)), 2, True, set())
    [far] = streams(roster, [clear], readings | _readings((clear, 30.0, 1)), 2, True, set())

    assert (near.pickup, near.drop) == ("keeper", "Weaker")
    assert "21.60" in near.reason
    assert "21.60" not in far.reason


def test_a_player_back_before_the_week_ends_stays_off_il() -> None:
    """In IL he would sit out the games he is back for, and activating him needs a drop of its own."""
    roster, readings = _team()
    out = _player("Out", "BN", status="O")
    readings |= {"Out": replace(_read(out, 25.0, 2), back=WED)}

    assert reserving([*roster, out], readings, ("IL",)) == []
    assert reserving([*roster, out], readings | {"Out": replace(readings["Out"], games=0)}, ()) == []


def test_a_stream_into_an_open_spot_lets_nobody_go() -> None:
    roster, readings = _team()
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 10.0, 4))

    [item] = streams(roster, [pickup], readings, 2, True, set(), plan=Plan(open_spots=1))

    assert (item.player_id, item.drop, item.pickup) == ("Pickup", "", "streamer")
    assert streams(roster, [pickup], readings | _readings((pickup, 10.0, 1)), 2, True, set(), Plan(open_spots=1)) == []


def test_a_falling_role_is_the_first_let_go() -> None:
    """Minutes down by six over his last five: his value a game still reads the role he had."""
    roster, readings = _team()
    readings["Weak"] = replace(readings["Weak"], role=Role(games=5, minutes=22.0, window=28.0))
    pickup = _player("Pickup", position="SF")
    readings |= _readings((pickup, 21.0, 4))

    assert [r.player.name for r in droppable(roster, readings, set())] == ["Weak", "Weaker"]
    [item] = streams(roster, [pickup], readings, 2, True, set())
    assert item.drop == "Weak"
    assert "22" in item.reason and "28" in item.reason


def test_a_role_grown_over_his_last_five_is_never_the_drop_however_cold_his_nights() -> None:
    """Coby White: minutes up, value a game still catching up with them."""
    roster, readings = _team()
    readings["Weaker"] = replace(readings["Weaker"], role=Role(games=5, minutes=27.0, window=21.0))

    assert [r.player.name for r in droppable(roster, readings, set())] == ["Weak"]


def test_a_game_time_call_counts_his_first_night_at_his_chance_of_playing_it() -> None:
    roster, readings = _team()
    fit, doubtful = (
        _player("Fit", position="SF", team="DET"),
        _player("Doubtful", position="SF", team="DET", status="GTD"),
    )
    readings |= _readings((fit, 10.0, 4), (doubtful, 10.0, 4))
    weigh = Weigh(roster, readings, Plan(week=DETROIT))

    sure, nights = weigh.gained(readings["Fit"], readings["Weak"])
    doubted, _ = weigh.gained(readings["Doubtful"], readings["Weak"])

    assert nights == 4
    assert doubted == sure - 10.0 * (1 - chance("GTD"))


# ── what a keeper does for the categories the roster is short of ───

GM3_SCALES = {
    label: Scale(scored=StatCategory(stat, name, fewer_wins=sign < 0), sign=sign, spread=spread, mean=mean)
    for label, stat, name, sign, spread, mean in (
        ("FG%", "5", "FG%", 1.0, 0.5274, 0.475),
        ("FT%", "8", "FT%", 1.0, 0.2949, 0.7918),
        ("3PTM", "10", "3PTM", 1.0, 0.8383, 1.4314),
        ("PTS", "12", "PTS", 1.0, 5.2546, 11.0586),
        ("REB", "15", "REB", 1.0, 2.0513, 4.161),
        ("AST", "16", "AST", 1.0, 1.4094, 2.3932),
        ("STL", "17", "ST", 1.0, 0.3591, 0.8675),
        ("BLK", "18", "BLK", 1.0, 0.476, 0.5369),
        ("TO", "19", "TO", -1.0, 0.7068, 1.2759),
    )
}
"""GM 3's categories on Tue 24 Nov, each scaled across that week's pool as the league read it."""

TURNER_LINE = {
    "PTS": 8.49,
    "REB": 5.95,
    "AST": 2.38,
    "STL": 0.58,
    "BLK": 2.11,
    "3PTM": 1.51,
    "FG%": 0.40,
    "FGA": 7.62,
    "FT%": 0.81,
    "FTA": 1.14,
    "TO": 1.78,
}
GOBERT_LINE = {
    "PTS": 7.98,
    "REB": 10.57,
    "AST": 1.75,
    "STL": 0.76,
    "BLK": 1.17,
    "3PTM": 0.0,
    "FG%": 0.51,
    "FGA": 5.65,
    "FT%": 0.47,
    "FTA": 4.6,
    "TO": 1.28,
}
"""Their lines a game as GM 3 read them: Turner is added for Gobert's free throws, and his own blocks and threes."""


def test_a_centres_assists_over_a_bigger_centres_are_not_named_as_help_with_assists() -> None:
    """GM 3: Turner over Gobert, short of AST, REB and ST. Turner has more assists than Gobert but no more than the
    pool's average, and gives up four rebounds a game: the item names the rebounds, never the assists."""
    roster, readings = _team()
    gobert = _player("Rudy Gobert", "BN", position="C", team="MIN")
    turner = _player("Myles Turner", position="C", team="MIL")
    readings |= {
        "Rudy Gobert": Reading(player=gobert, line=GOBERT_LINE, per_game=5.5, games=3),
        "Myles Turner": Reading(player=turner, line=TURNER_LINE, per_game=10.5, games=3),
    }
    weights = {label: 1.0 if label in {"AST", "REB", "STL"} else UNNEEDED for label in GM3_SCALES}
    plan = Plan(needs=Targeting(scales=GM3_SCALES, weights=weights))

    swap = Weigh([*roster, gobert], readings, plan).keeper(readings["Myles Turner"], readings["Rudy Gobert"])
    [item] = streams([*roster, gobert], [turner], readings, 1, False, set(), plan=plan)

    assert swap is not None
    assert swap.targets == ()
    assert swap.costs[0] == "REB"
    assert (item.player_id, item.drop, item.pickup) == ("Myles Turner", "Rudy Gobert", "keeper")
    assert "REB" in item.reason
