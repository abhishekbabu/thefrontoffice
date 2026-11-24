"""Tests for the FPL lineup and transfer arithmetic.

These are the parts with exact answers, so they are asserted exactly rather
than left to the model.
"""

from datetime import UTC, datetime

import pytest
from support.fpl import effective_points, player

from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    MAX_FREE_TRANSFERS,
    Roster,
    Transfer,
    affordable_transfers,
    armbands,
    best_lineup,
    club_counts,
    fixtures_by_club,
    formations,
    free_transfers,
    likely,
    lineup_changes,
    plays,
    points_of,
    points_with_captain,
    purchase_prices,
    room_at,
    roster,
    selling_price,
    substitution_chances,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    FORMATION_LIMITS,
    STARTING_SIZE,
    ChipPlay,
    Fixture,
    GameweekResult,
    LiveStat,
    Pick,
    Player,
    Squad,
    TransferMade,
)


def squad_of(*specs: tuple[str, float]) -> list[Player]:
    return [player(i, position, points) for i, (position, points) in enumerate(specs, start=1)]


FIFTEEN = squad_of(
    ("GKP", 5.0),
    ("GKP", 2.0),
    ("DEF", 6.0),
    ("DEF", 5.5),
    ("DEF", 5.0),
    ("DEF", 1.0),
    ("DEF", 0.5),
    ("MID", 8.0),
    ("MID", 7.0),
    ("MID", 6.5),
    ("MID", 6.0),
    ("MID", 1.5),
    ("FWD", 9.0),
    ("FWD", 4.0),
    ("FWD", 3.0),
)


# ── formations ──────────────────────────────────────────────────────────


def test_the_familiar_shapes_are_all_present() -> None:
    shapes = {(s["DEF"], s["MID"], s["FWD"]) for s in formations()}
    assert {(4, 4, 2), (3, 5, 2), (5, 3, 2), (3, 4, 3), (4, 3, 3)} <= shapes


# ── the best eleven ─────────────────────────────────────────────────────


def test_the_best_eleven_leaves_the_weakest_four_out() -> None:
    lineup = best_lineup(FIFTEEN, effective_points)
    assert {p.id for p in lineup.bench} == {2, 6, 7, 12}
    assert lineup.formation == "3-4-3"


def test_the_captain_is_the_highest_expecting_starter_and_counts_twice() -> None:
    lineup = best_lineup(FIFTEEN, effective_points)
    assert lineup.captain is not None and lineup.captain.id == 13
    assert lineup.points == 74.0  # 65.0 across the eleven, and the captain's 9.0 again


def test_taking_the_best_eleven_outright_would_be_illegal() -> None:
    """The guard the formation search exists for.

    With a strong midfield and a weak defense, the eleven highest projections
    field two defenders, which is not a shape the game will accept.
    """
    squad = squad_of(
        ("GKP", 5.0),
        ("GKP", 1.0),
        ("DEF", 6.0),
        ("DEF", 5.5),
        ("DEF", 0.6),
        ("DEF", 0.4),
        ("DEF", 0.2),
        ("MID", 9.0),
        ("MID", 8.5),
        ("MID", 8.0),
        ("MID", 7.5),
        ("MID", 7.0),
        ("FWD", 9.5),
        ("FWD", 6.5),
        ("FWD", 6.0),
    )
    top_eleven = sorted(squad, key=lambda p: -p.expected_points)[:STARTING_SIZE]
    assert sum(p.position == "DEF" for p in top_eleven) < FORMATION_LIMITS["DEF"][0]
    assert sum(p.position == "DEF" for p in best_lineup(squad, effective_points).starters) == FORMATION_LIMITS["DEF"][0]


def test_a_ruled_out_star_is_benched_for_a_fit_squad_player() -> None:
    squad = [p for p in FIFTEEN if p.id != 8] + [player(8, "MID", 8.0, chance_of_playing=0)]
    starters = {p.id for p in best_lineup(squad, effective_points).starters}
    assert 8 not in starters
    assert 12 in starters


def test_the_reserve_goalkeeper_sits_apart_from_the_outfield_bench() -> None:
    """Auto-subs can only replace a goalkeeper with a goalkeeper."""
    assert best_lineup(FIFTEEN, effective_points).bench[0].position == "GKP"


def test_the_rest_of_the_bench_is_in_expected_points_order() -> None:
    outfield = best_lineup(FIFTEEN, effective_points).bench[1:]
    assert [p.expected_points for p in outfield] == sorted((p.expected_points for p in outfield), reverse=True)


def test_a_squad_too_short_for_any_formation_yields_nothing() -> None:
    lineup = best_lineup(squad_of(("GKP", 5.0), ("MID", 4.0)), effective_points)
    assert lineup.starters == []
    assert lineup.captain is None
    assert lineup.points == 0.0


# ── auto-subs ───────────────────────────────────────────────────────────


def _three_four_three(**misses: float) -> list[tuple[str, float]]:
    """A 3-4-3 by position, every starter certain to play unless named: `DEF1=1.0` rules the first defender out."""
    shape = [("GKP", 1), ("DEF", 3), ("MID", 4), ("FWD", 3)]
    return [(pos, misses.get(f"{pos}{n}", 0.0)) for pos, count in shape for n in range(1, count + 1)]


def test_a_substitute_who_would_leave_two_defenders_is_passed_over_for_the_next() -> None:
    bench = [("GKP", 0.0), ("MID", 0.0), ("FWD", 0.0), ("DEF", 0.0)]
    assert substitution_chances(_three_four_three(DEF1=1.0), bench) == [0.0, 0.0, 0.0, 1.0]


def test_the_reserve_keeper_comes_on_for_the_keeper_and_for_nobody_else() -> None:
    bench = [("GKP", 0.0), ("MID", 0.0), ("FWD", 0.0), ("DEF", 0.0)]
    assert substitution_chances(_three_four_three(GKP1=1.0), bench) == [1.0, 0.0, 0.0, 0.0]
    assert substitution_chances(_three_four_three(MID1=1.0), bench) == [0.0, 1.0, 0.0, 0.0]


def test_the_bench_comes_on_in_order_passing_over_one_who_does_not_play() -> None:
    fit = [("GKP", 0.0), ("MID", 0.0), ("FWD", 0.0), ("DEF", 0.0)]
    first_out = [("GKP", 0.0), ("MID", 1.0), ("FWD", 0.0), ("DEF", 0.0)]

    assert substitution_chances(_three_four_three(FWD1=1.0), fit) == [0.0, 1.0, 0.0, 0.0]
    assert substitution_chances(_three_four_three(FWD1=1.0), first_out) == [0.0, 0.0, 1.0, 0.0]


def test_a_reserve_keeper_who_does_not_play_himself_never_comes_on() -> None:
    bench = [("GKP", 1.0), ("MID", 0.0), ("FWD", 0.0), ("DEF", 0.0)]
    assert substitution_chances(_three_four_three(GKP1=1.0), bench)[0] == 0.0


def test_doubts_bring_the_bench_on_with_the_chance_enough_of_them_miss() -> None:
    """Two defenders each at evens: one or more miss three times in four, both once in four."""
    bench = [("GKP", 0.0), ("DEF", 0.0), ("DEF", 0.0), ("MID", 0.0)]
    chances = substitution_chances(_three_four_three(DEF1=0.5, DEF2=0.5), bench)

    assert chances == pytest.approx([0.0, 0.75, 0.25, 0.0])


def test_a_doubtful_substitute_comes_on_only_as_often_as_he_plays() -> None:
    bench = [("GKP", 0.0), ("MID", 0.5), ("FWD", 0.0), ("DEF", 0.0)]
    chances = substitution_chances(_three_four_three(MID1=1.0), bench)

    assert chances == pytest.approx([0.0, 0.5, 0.5, 0.0])  # the forward behind him covers the half he misses


# ── changes ─────────────────────────────────────────────────────────────


def test_no_changes_when_the_eleven_is_already_best() -> None:
    best = best_lineup(FIFTEEN, effective_points)
    assert lineup_changes(best.starters, best, effective_points) == []


def test_a_change_pairs_the_player_coming_in_with_the_one_going_out() -> None:
    best = best_lineup(FIFTEEN, effective_points)
    current = [p for p in best.starters if p.id != 13] + [next(p for p in FIFTEEN if p.id == 12)]

    changes = lineup_changes(current, best, effective_points)
    assert [(c.start.id, c.drop.id if c.drop else None) for c in changes] == [(13, 12)]
    assert changes[0].gain == 7.5  # 9.0 coming in for 1.5


def test_changes_are_ordered_by_what_they_gain() -> None:
    best = best_lineup(FIFTEEN, effective_points)
    current = [p for p in best.starters if p.id not in (11, 13)] + [
        next(p for p in FIFTEEN if p.id == 12),
        next(p for p in FIFTEEN if p.id == 7),
    ]
    gains = [c.gain for c in lineup_changes(current, best, effective_points)]
    assert gains == sorted(gains, reverse=True)


def _counts(eleven: list[Player]) -> dict[str, int]:
    return {pos: sum(p.position == pos for p in eleven) for pos in FORMATION_LIMITS}


def _apply(eleven: list[Player], start: Player, drop: Player | None) -> list[Player]:
    return [p for p in eleven if drop is None or p.id != drop.id] + [start]


def _legal(eleven: list[Player]) -> bool:
    return all(low <= _counts(eleven)[pos] <= high for pos, (low, high) in FORMATION_LIMITS.items())


# A keeper change and a defender change at once, with the incoming keeper the
# strongest player coming in and the outgoing defender the weakest going out —
# the shape that once paired a keeper for a defender and fielded two keepers.
KEEPERS_AND_BACKS = [
    player(1, "GKP", 2.0),  # starts, should not
    player(2, "GKP", 6.0),  # benched, should start
    player(3, "DEF", 1.0),  # starts, should not
    player(4, "DEF", 4.0),  # benched, should start
    *[player(10 + i, "DEF", 5.0) for i in range(3)],
    *[player(20 + i, "MID", 5.0) for i in range(5)],
    player(30, "FWD", 5.0),
    player(31, "FWD", 0.2),
    player(40, "FWD", 0.1),
]
SET_ELEVEN = {1, 3, 10, 11, 12, 20, 21, 22, 23, 24, 30}


def test_a_keeper_is_only_ever_swapped_for_a_keeper() -> None:
    best = best_lineup(KEEPERS_AND_BACKS, effective_points)
    current = [p for p in KEEPERS_AND_BACKS if p.id in SET_ELEVEN]

    pairs = {(c.start.id, c.drop.id if c.drop else None) for c in lineup_changes(current, best, effective_points)}

    assert pairs == {(2, 1), (4, 3)}


def test_a_change_of_formation_swaps_across_positions_and_stays_legal_at_every_step() -> None:
    """A 5-4-1 whose best shape is 3-4-3: two defenders out, two forwards in, in either order."""
    squad = [
        player(1, "GKP", 5.0),
        player(2, "GKP", 1.0),
        *[player(10 + i, "DEF", 5.0) for i in range(3)],
        player(13, "DEF", 1.0),
        player(14, "DEF", 1.5),
        *[player(20 + i, "MID", 5.0) for i in range(4)],
        player(24, "MID", 0.5),
        player(30, "FWD", 6.0),
        player(31, "FWD", 4.0),
        player(32, "FWD", 3.0),
    ]
    best = best_lineup(squad, effective_points)
    current = [p for p in squad if p.id in {1, 10, 11, 12, 13, 14, 20, 21, 22, 23, 30}]
    changes = lineup_changes(current, best, effective_points)

    assert sorted((c.start.position, c.drop.position if c.drop else "") for c in changes) == [
        ("FWD", "DEF"),
        ("FWD", "DEF"),
    ]
    for order in (changes, list(reversed(changes))):
        eleven = list(current)
        for change in order:
            eleven = _apply(eleven, change.start, change.drop)
            assert _legal(eleven)


def test_the_swaps_listed_reach_the_best_elevens_total() -> None:
    """Nothing filtered on its own gain, so the list adds up to what the headline promises."""
    best = best_lineup(KEEPERS_AND_BACKS, effective_points)
    current = [p for p in KEEPERS_AND_BACKS if p.id in SET_ELEVEN]

    gained = sum(c.gain for c in lineup_changes(current, best, effective_points))

    assert round(gained, 2) == round(
        points_with_captain(best.starters, None, effective_points)
        - points_with_captain(current, None, effective_points),
        2,
    )


# ── transfers ───────────────────────────────────────────────────────────


def test_a_transfer_prices_the_incoming_player_against_the_outgoing_sale() -> None:
    transfer = Transfer(out=player(1, "MID", 3.0, cost=50), incoming=player(2, "MID", 6.0, cost=85), sale=48, gain=3.0)
    assert transfer.cost == 37


def test_a_cheaper_incoming_player_frees_money() -> None:
    transfer = Transfer(out=player(1, "MID", 3.0, cost=85), incoming=player(2, "MID", 6.0, cost=50), sale=85, gain=3.0)
    assert transfer.cost == -35


def test_only_what_the_bank_can_pay_for_is_offered() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=120), player(3, "MID", 5.0, cost=55)]
    assert [
        t.incoming.id
        for t in affordable_transfers(squad, market, bank=10, selling={}, limit=10, value=effective_points)
    ] == [3]


def test_a_player_kept_is_never_sold_and_the_target_goes_to_whoever_else_he_improves_on() -> None:
    squad = [player(1, "MID", 3.0, cost=50), player(4, "MID", 4.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=50)]

    [transfer] = affordable_transfers(squad, market, bank=0, selling={}, limit=10, value=effective_points, keep={"1"})

    assert (transfer.out.id, transfer.incoming.id) == (4, 2)


def test_a_rise_kept_back_by_the_sell_on_fee_can_put_a_target_out_of_reach() -> None:
    """Priced at £5.5m he would fund the £6.0m target; he sells for £5.2m, so he cannot."""
    squad = [player(1, "MID", 3.0, cost=55)]
    market = [player(2, "MID", 9.0, cost=60)]
    assert affordable_transfers(squad, market, bank=5, selling={}, limit=10, value=effective_points)
    assert affordable_transfers(squad, market, bank=5, selling={1: 52}, limit=10, value=effective_points) == []


# ── selling prices ──────────────────────────────────────────────────────


def test_a_rise_is_halved_and_rounded_down() -> None:
    assert selling_price(bought=75, now=78) == 76
    assert selling_price(bought=75, now=79) == 77


def test_a_fall_is_passed_on_in_full() -> None:
    assert selling_price(bought=75, now=72) == 72


def _bought(element: int, cost: int, event: int, day: int) -> TransferMade:
    return TransferMade(
        element_in=element, element_in_cost=cost, element_out=0, event=event, time=datetime(2026, 9, day, tzinfo=UTC)
    )


def test_the_latest_purchase_sets_the_price() -> None:
    owned = [player(1, "MID", 5.0, cost=80)]
    transfers = [_bought(1, 76, event=6, day=20), _bought(1, 70, event=2, day=1)]
    assert purchase_prices(owned, transfers, chips=[]) == {1: 76}


def test_a_free_hit_weeks_purchases_are_undone() -> None:
    owned = [player(1, "MID", 5.0, cost=80)]
    transfers = [_bought(1, 70, event=2, day=1), _bought(1, 79, event=6, day=20)]
    assert purchase_prices(owned, transfers, chips=[ChipPlay(name="freehit", event=6)]) == {1: 70}


def test_a_player_never_transferred_in_was_bought_at_the_seasons_opening_price() -> None:
    from dataclasses import replace

    owned = [replace(player(1, "MID", 5.0, cost=80), start_cost=75), player(2, "MID", 5.0, cost=60)]
    assert purchase_prices(owned, [], chips=[]) == {1: 75, 2: 60}


def test_a_swap_across_positions_is_never_offered() -> None:
    """A squad holds a fixed count of each position, so like replaces like."""
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "FWD", 9.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points) == []


def test_a_player_already_in_the_squad_is_not_offered_back() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, list(squad), bank=100, selling={}, limit=10, value=effective_points) == []


def test_an_unavailable_target_is_not_offered() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=50, status="i")]
    assert affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points) == []


def test_a_downgrade_is_not_offered() -> None:
    squad = [player(1, "MID", 6.0, cost=50)]
    market = [player(2, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points) == []


def test_each_target_appears_once_against_whoever_it_most_improves() -> None:
    """Otherwise one premium striker fills the list opposite every forward."""
    squad = [player(1, "FWD", 2.0, cost=50), player(2, "FWD", 3.0, cost=50)]
    market = [player(9, "FWD", 9.0, cost=50)]
    transfers = affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points)
    assert [(t.incoming.id, t.out.id) for t in transfers] == [(9, 1)]


def test_one_squad_player_cannot_monopolise_the_list() -> None:
    """Eight ways to replace the same weak link is one suggestion, not eight."""
    squad = [player(1, "MID", 0.5, cost=40), player(2, "DEF", 4.0, cost=40)]
    market = [player(10 + i, "MID", 8.0 - i * 0.1, cost=40) for i in range(8)]
    market.append(player(30, "DEF", 6.0, cost=40))

    transfers = affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points)
    assert sum(t.out.id == 1 for t in transfers) == 3
    assert [t.incoming.id for t in transfers if t.out.id == 2] == [30]


def test_the_best_upgrades_come_first() -> None:
    squad = [player(1, "MID", 1.0, cost=40), player(2, "DEF", 1.0, cost=40)]
    market = [player(10, "MID", 4.0, cost=40), player(11, "DEF", 9.0, cost=40)]
    assert [
        t.incoming.id
        for t in affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points)
    ] == [11, 10]


# ── comparing two elevens ───────────────────────────────────────────────


def test_a_captained_total_counts_its_captain_twice() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, starters[1], effective_points) == 21.0


def test_an_uncaptained_total_is_the_plain_sum() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, None, effective_points) == 13.0


def test_a_ruled_out_captain_adds_nothing() -> None:
    starters = [player(1, "MID", 5.0), player(2, "FWD", 8.0, chance_of_playing=0)]
    assert points_with_captain(starters, starters[1], effective_points) == 5.0


# ── who plays ───────────────────────────────────────────────────────────


def test_a_doubt_still_plays() -> None:
    """Flagged beside the player, not ruled out — the market and the lineups read the same rule."""
    assert plays(player(1, "MID", 6.0, status="d", chance_of_playing=50))


def test_a_ruled_out_status_or_a_nought_percent_does_not_play() -> None:
    assert not plays(player(1, "MID", 6.0, status="u"))
    assert not plays(player(1, "MID", 6.0, status="n"))
    assert not plays(player(1, "MID", 6.0, status="d", chance_of_playing=0))


def test_a_doubtful_target_is_offered_as_a_transfer() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=50, status="d", chance_of_playing=75)]
    assert [
        t.incoming.id
        for t in affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points)
    ] == [2]


# ── free transfers ──────────────────────────────────────────────────────


def _played(event: int, transfers: int = 0) -> GameweekResult:
    return GameweekResult(event=event, points=50, transfers_made=transfers, transfers_cost=0)


def test_one_free_transfer_in_the_opening_gameweek() -> None:
    assert free_transfers([], upcoming=1, chips=[]) == 1


def test_the_squad_is_picked_free_and_the_first_transfer_arrives_after_it() -> None:
    assert free_transfers([_played(1)], upcoming=2, chips=[]) == 1


def test_an_unused_transfer_rolls_over() -> None:
    assert free_transfers([_played(1), _played(2)], upcoming=3, chips=[]) == 2


def test_using_the_allowance_resets_it_to_one() -> None:
    assert free_transfers([_played(1), _played(2, transfers=1)], upcoming=3, chips=[]) == 1


def test_rollover_is_capped() -> None:
    """Five is the ceiling however long a manager sits on their hands."""
    assert free_transfers([_played(e) for e in range(1, 12)], upcoming=12, chips=[]) == MAX_FREE_TRANSFERS


def test_a_gameweek_of_hits_never_drops_below_one() -> None:
    assert free_transfers([_played(1), _played(2, transfers=4)], upcoming=3, chips=[]) == 1


def test_a_late_joiners_first_gameweek_is_the_one_their_squad_was_picked_for() -> None:
    """A manager who joined late has no row before they started, and one transfer after it."""
    assert free_transfers([_played(3)], upcoming=4, chips=[]) == 1


def test_a_wildcard_or_free_hit_week_leaves_the_bank_where_it_was() -> None:
    """Its transfers are free, and it earns none: two banked going in, two coming out."""
    history = [_played(1), _played(2), _played(3)]
    for chip in ("wildcard", "freehit"):
        assert free_transfers(history, upcoming=4, chips=[ChipPlay(name=chip, event=3)]) == 2


def test_a_bench_boost_week_counts_like_any_other() -> None:
    history = [_played(1), _played(2), _played(3)]
    assert free_transfers(history, upcoming=4, chips=[ChipPlay(name="bboost", event=3)]) == 3


def test_a_wildcard_after_a_transfer_every_week_leaves_two_for_the_week_after_next() -> None:
    """One transfer a week for GW2-8, a GW9 Wildcard and a quiet GW10, as one real 2026/27 entry played it."""
    history = [_played(1), *(_played(e, transfers=1) for e in range(2, 9)), _played(9), _played(10)]
    chips = [ChipPlay(name="3xc", event=3), ChipPlay(name="wildcard", event=9)]
    assert free_transfers(history, upcoming=11, chips=chips) == 2


# ── what a fielded squad scores ─────────────────────────────────────────

FIELDED = {1: player(1, "MID", 5.0), 2: player(2, "FWD", 8.0), 3: player(3, "DEF", 2.0)}


def _fielded(*multipliers: int) -> Roster:
    """Players 1 and 2 start, 3 sits on the bench; the multipliers are the game's own."""
    picks = [
        Pick(element=pid, position=pid if pid < 3 else 12, multiplier=m, is_captain=m >= 2)
        for pid, m in zip(FIELDED, multipliers, strict=True)
    ]
    return roster(Squad(gameweek=4, picks=picks, bank=0, value=0), FIELDED)


SCORED = {1: LiveStat(points=5, minutes=90), 2: LiveStat(points=10, minutes=90), 3: LiveStat(points=6, minutes=90)}


def test_each_pick_counts_by_its_multiplier() -> None:
    """Captain twice, starter once, bench not at all."""
    assert _fielded(1, 2, 0).scored(SCORED) == 25


def test_a_triple_captain_counts_three_times() -> None:
    assert _fielded(1, 3, 0).scored(SCORED) == 35


def test_a_bench_boost_counts_the_bench() -> None:
    assert _fielded(1, 2, 1).scored(SCORED) == 31


def test_nothing_is_scored_before_anyone_counted_has_played() -> None:
    """None rather than nought, which reads as a bad week instead of one not yet started."""
    benched_only = {3: LiveStat(points=6, minutes=90)}
    assert _fielded(1, 2, 0).scored(benched_only) is None


def test_a_benched_row_shows_what_he_scored() -> None:
    assert points_of(Pick(element=3, position=12, multiplier=0), LiveStat(points=6, minutes=90)) == 6


def test_the_captain_is_read_off_the_armband() -> None:
    fielded = _fielded(1, 2, 0)
    assert fielded.captain is FIELDED[2]
    assert [p.id for p in fielded.starters] == [1, 2]
    assert [p.id for p in fielded.bench] == [3]


# ── fixtures ────────────────────────────────────────────────────────────


def test_a_club_with_no_match_is_a_blank_and_two_is_a_double() -> None:
    fixtures = [
        Fixture(event=5, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4),
        Fixture(event=5, home="MCI", away="ARS", home_difficulty=3, away_difficulty=5),
    ]
    by_club = fixtures_by_club(fixtures, ["ARS", "TOT", "ARS"])

    assert by_club["TOT"] == []
    assert [(m.club, m.difficulty, m.home) for m in by_club["ARS"]] == [("LIV", 2, True), ("MCI", 5, False)]


# ── the armband ─────────────────────────────────────────────────────────


def test_a_player_flagged_below_three_in_four_is_not_counted_on_to_start() -> None:
    assert likely(player(1, "MID", 6.0))
    assert likely(player(1, "MID", 6.0, status="d", chance_of_playing=75))
    assert not likely(player(1, "MID", 6.0, status="d", chance_of_playing=50))
    assert not likely(player(1, "MID", 6.0, status="i"))


def test_the_armband_never_goes_to_a_starter_unlikely_to_play_however_much_he_is_worth() -> None:
    doubtful = player(1, "FWD", 12.0, status="d", chance_of_playing=50)
    starters = [doubtful, player(2, "MID", 7.0), player(3, "DEF", 5.0)]

    assert armbands(starters, effective_points) == (starters[1], starters[2])


def test_with_too_few_starters_likely_the_rest_make_up_the_pair_best_first() -> None:
    starters = [player(1, "FWD", 12.0, status="d", chance_of_playing=50), player(2, "MID", 7.0)]

    assert armbands(starters, effective_points) == (starters[1], starters[0])


def test_the_best_eleven_names_a_vice_as_well_as_a_captain() -> None:
    lineup = best_lineup(FIFTEEN, effective_points)

    assert lineup.captain is not None and lineup.vice is not None
    assert (lineup.captain.points_per_game, lineup.vice.points_per_game) == (9.0, 8.0)


def test_the_vice_is_read_off_the_armband() -> None:
    picks = [Pick(element=1, position=1, multiplier=1, is_vice_captain=True), Pick(element=2, position=2, multiplier=2)]
    catalog = {1: player(1, "MID", 5.0), 2: player(2, "FWD", 6.0)}

    assert roster(Squad(gameweek=4, picks=picks, bank=0, value=0), catalog).vice is catalog[1]


def test_the_eleven_is_picked_on_the_value_it_is_given() -> None:
    """The projection says the 9.0 forward captains; a value that rates the 1.5 midfielder higher captains him."""
    lineup = best_lineup(FIFTEEN, lambda p: 20.0 if p.id == 12 else effective_points(p))

    assert lineup.captain is not None and lineup.captain.id == 12


# ── club places ─────────────────────────────────────────────────────────


def test_no_transfer_brings_in_a_fourth_player_from_one_club() -> None:
    squad = [player(i, "MID", 3.0, cost=50, team="LIV") for i in (1, 2, 3)] + [player(4, "MID", 3.0, team="ARS")]
    market = [player(10, "MID", 9.0, cost=50, team="LIV")]

    found = affordable_transfers(squad, market, bank=100, selling={}, limit=10, value=effective_points)

    assert [t.out.team for t in found] == ["LIV"]  # only ever for one of his own club's three
    assert club_counts(squad) == {"LIV": 3, "ARS": 1}
    assert room_at({"LIV": 2}, market[0], squad[3])
