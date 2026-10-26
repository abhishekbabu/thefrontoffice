"""Tests for the FPL lineup and transfer arithmetic.

These are the parts with exact answers, so they are asserted exactly rather
than left to the model.
"""

from thefrontoffice.adapters.outbound.competitions.premier_league.squad import (
    Transfer,
    affordable_transfers,
    best_lineup,
    effective_points,
    formations,
    lineup_changes,
    points_with_captain,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import FORMATION_LIMITS, STARTING_SIZE, Player


def player(
    pid: int,
    position: str,
    points: float,
    cost: int = 50,
    status: str = "a",
    chance: int | None = None,
    team: str = "ARS",
) -> Player:
    return Player(
        id=pid,
        name=f"P{pid}",
        full_name=f"Player {pid}",
        position=position,
        team=team,
        cost=cost,
        expected_points=points,
        form=points,
        points_per_game=points,
        total_points=int(points * 10),
        selected_by=5.0,
        status=status,
        chance_of_playing=chance,
        minutes=900,
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


# ── availability ────────────────────────────────────────────────────────


def test_a_ruled_out_player_is_worth_nothing() -> None:
    """The game leaves a stale projection on a player it has already ruled out."""
    assert effective_points(player(1, "MID", 6.0, chance=0)) == 0.0
    assert effective_points(player(1, "MID", 6.0, status="i")) == 0.0
    assert effective_points(player(1, "MID", 6.0, status="s")) == 0.0


def test_a_doubt_is_not_a_ruling_out() -> None:
    assert effective_points(player(1, "MID", 6.0, status="d", chance=75)) == 6.0


# ── formations ──────────────────────────────────────────────────────────


def test_every_formation_is_legal_and_fields_eleven() -> None:
    shapes = formations()
    assert shapes
    for shape in shapes:
        assert sum(shape.values()) == STARTING_SIZE
        for position, count in shape.items():
            low, high = FORMATION_LIMITS[position]
            assert low <= count <= high


def test_the_familiar_shapes_are_all_present() -> None:
    shapes = {(s["DEF"], s["MID"], s["FWD"]) for s in formations()}
    assert {(4, 4, 2), (3, 5, 2), (5, 3, 2), (3, 4, 3), (4, 3, 3)} <= shapes


# ── the best eleven ─────────────────────────────────────────────────────


def test_the_best_eleven_is_legal() -> None:
    lineup = best_lineup(FIFTEEN)
    assert len(lineup.starters) == STARTING_SIZE
    counts = {position: sum(p.position == position for p in lineup.starters) for position in FORMATION_LIMITS}
    for position, count in counts.items():
        low, high = FORMATION_LIMITS[position]
        assert low <= count <= high


def test_the_best_eleven_leaves_the_weakest_four_out() -> None:
    lineup = best_lineup(FIFTEEN)
    assert {p.id for p in lineup.bench} == {2, 6, 7, 12}
    assert lineup.formation == "3-4-3"


def test_the_captain_is_the_highest_expecting_starter_and_counts_twice() -> None:
    lineup = best_lineup(FIFTEEN)
    assert lineup.captain is not None and lineup.captain.id == 13
    assert lineup.points == round(sum(p.expected_points for p in lineup.starters) + 9.0, 2)


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
    assert sum(p.position == "DEF" for p in best_lineup(squad).starters) == FORMATION_LIMITS["DEF"][0]


def test_a_ruled_out_star_is_benched_for_a_fit_squad_player() -> None:
    squad = [p for p in FIFTEEN if p.id != 8] + [player(8, "MID", 8.0, chance=0)]
    starters = {p.id for p in best_lineup(squad).starters}
    assert 8 not in starters
    assert 12 in starters


def test_the_reserve_goalkeeper_sits_apart_from_the_outfield_bench() -> None:
    """Auto-subs can only replace a goalkeeper with a goalkeeper."""
    assert best_lineup(FIFTEEN).bench[0].position == "GKP"


def test_the_rest_of_the_bench_is_in_expected_points_order() -> None:
    outfield = best_lineup(FIFTEEN).bench[1:]
    assert [p.expected_points for p in outfield] == sorted((p.expected_points for p in outfield), reverse=True)


def test_a_squad_too_short_for_any_formation_yields_nothing() -> None:
    lineup = best_lineup(squad_of(("GKP", 5.0), ("MID", 4.0)))
    assert lineup.starters == []
    assert lineup.captain is None
    assert lineup.points == 0.0


# ── changes ─────────────────────────────────────────────────────────────


def test_no_changes_when_the_eleven_is_already_best() -> None:
    best = best_lineup(FIFTEEN)
    assert lineup_changes(best.starters, best) == []


def test_a_change_pairs_the_player_coming_in_with_the_one_going_out() -> None:
    best = best_lineup(FIFTEEN)
    benched_star = next(p for p in best.starters if p.id == 13)
    current = [p for p in best.starters if p.id != 13] + [next(p for p in FIFTEEN if p.id == 12)]

    changes = lineup_changes(current, best)
    assert [(c.start.id, c.drop.id if c.drop else None) for c in changes] == [(13, 12)]
    assert changes[0].gain == round(benched_star.expected_points - 1.5, 2)


def test_changes_are_ordered_by_what_they_gain() -> None:
    best = best_lineup(FIFTEEN)
    current = [p for p in best.starters if p.id not in (11, 13)] + [
        next(p for p in FIFTEEN if p.id == 12),
        next(p for p in FIFTEEN if p.id == 7),
    ]
    gains = [c.gain for c in lineup_changes(current, best)]
    assert gains == sorted(gains, reverse=True)


# ── transfers ───────────────────────────────────────────────────────────


def test_a_transfer_prices_the_difference_between_the_two() -> None:
    transfer = Transfer(out=player(1, "MID", 3.0, cost=50), incoming=player(2, "MID", 6.0, cost=85))
    assert transfer.cost == 35
    assert transfer.gain == 3.0


def test_a_cheaper_incoming_player_frees_money() -> None:
    transfer = Transfer(out=player(1, "MID", 3.0, cost=85), incoming=player(2, "MID", 6.0, cost=50))
    assert transfer.cost == -35


def test_only_what_the_bank_can_pay_for_is_offered() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=120), player(3, "MID", 5.0, cost=55)]
    assert [t.incoming.id for t in affordable_transfers(squad, market, bank=10)] == [3]


def test_a_swap_across_positions_is_never_offered() -> None:
    """A squad holds a fixed count of each position, so like replaces like."""
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "FWD", 9.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100) == []


def test_a_player_already_in_the_squad_is_not_offered_back() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, list(squad), bank=100) == []


def test_an_unavailable_target_is_not_offered() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=50, status="i")]
    assert affordable_transfers(squad, market, bank=100) == []


def test_a_downgrade_is_not_offered() -> None:
    squad = [player(1, "MID", 6.0, cost=50)]
    market = [player(2, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100) == []


def test_each_target_appears_once_against_whoever_it_most_improves() -> None:
    """Otherwise one premium striker fills the list opposite every forward."""
    squad = [player(1, "FWD", 2.0, cost=50), player(2, "FWD", 3.0, cost=50)]
    market = [player(9, "FWD", 9.0, cost=50)]
    transfers = affordable_transfers(squad, market, bank=100)
    assert [(t.incoming.id, t.out.id) for t in transfers] == [(9, 1)]


def test_one_squad_player_cannot_monopolise_the_list() -> None:
    """Eight ways to replace the same weak link is one suggestion, not eight."""
    squad = [player(1, "MID", 0.5, cost=40), player(2, "DEF", 4.0, cost=40)]
    market = [player(10 + i, "MID", 8.0 - i * 0.1, cost=40) for i in range(8)]
    market.append(player(30, "DEF", 6.0, cost=40))

    transfers = affordable_transfers(squad, market, bank=100)
    assert sum(t.out.id == 1 for t in transfers) == 3
    assert [t.incoming.id for t in transfers if t.out.id == 2] == [30]


def test_the_best_upgrades_come_first() -> None:
    squad = [player(1, "MID", 1.0, cost=40), player(2, "DEF", 1.0, cost=40)]
    market = [player(10, "MID", 4.0, cost=40), player(11, "DEF", 9.0, cost=40)]
    assert [t.incoming.id for t in affordable_transfers(squad, market, bank=100)] == [11, 10]


# ── comparing two elevens ───────────────────────────────────────────────


def test_a_captained_total_counts_its_captain_twice() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, starters[1]) == 21.0


def test_an_uncaptained_total_is_the_plain_sum() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, None) == 13.0


def test_a_ruled_out_captain_adds_nothing() -> None:
    starters = [player(1, "MID", 5.0), player(2, "FWD", 8.0, chance=0)]
    assert points_with_captain(starters, starters[1]) == 5.0
