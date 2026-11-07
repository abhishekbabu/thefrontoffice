"""Tests for the FPL lineup and transfer arithmetic.

These are the parts with exact answers, so they are asserted exactly rather
than left to the model.
"""

from support.fpl import player

from thefrontoffice.adapters.outbound.competitions.premier_league.squad import (
    MAX_FREE_TRANSFERS,
    Roster,
    Transfer,
    affordable_transfers,
    best_lineup,
    effective_points,
    fixtures_by_club,
    formations,
    free_transfers,
    lineup_changes,
    plays,
    points_of,
    points_with_captain,
    roster,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    FORMATION_LIMITS,
    STARTING_SIZE,
    Fixture,
    GameweekResult,
    LiveStat,
    Pick,
    Player,
    Squad,
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
    assert effective_points(player(1, "MID", 6.0, chance_of_playing=0)) == 0.0
    assert effective_points(player(1, "MID", 6.0, status="i")) == 0.0
    assert effective_points(player(1, "MID", 6.0, status="s")) == 0.0


def test_a_doubt_is_not_a_ruling_out() -> None:
    assert effective_points(player(1, "MID", 6.0, status="d", chance_of_playing=75)) == 6.0


# ── formations ──────────────────────────────────────────────────────────


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
    assert sum(p.position == "DEF" for p in best_lineup(squad).starters) == FORMATION_LIMITS["DEF"][0]


def test_a_ruled_out_star_is_benched_for_a_fit_squad_player() -> None:
    squad = [p for p in FIFTEEN if p.id != 8] + [player(8, "MID", 8.0, chance_of_playing=0)]
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
    current = [p for p in best.starters if p.id != 13] + [next(p for p in FIFTEEN if p.id == 12)]

    changes = lineup_changes(current, best)
    assert [(c.start.id, c.drop.id if c.drop else None) for c in changes] == [(13, 12)]
    assert changes[0].gain == 7.5  # 9.0 coming in for 1.5


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
    assert [t.incoming.id for t in affordable_transfers(squad, market, bank=10, limit=10)] == [3]


def test_a_swap_across_positions_is_never_offered() -> None:
    """A squad holds a fixed count of each position, so like replaces like."""
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "FWD", 9.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100, limit=10) == []


def test_a_player_already_in_the_squad_is_not_offered_back() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, list(squad), bank=100, limit=10) == []


def test_an_unavailable_target_is_not_offered() -> None:
    squad = [player(1, "MID", 3.0, cost=50)]
    market = [player(2, "MID", 9.0, cost=50, status="i")]
    assert affordable_transfers(squad, market, bank=100, limit=10) == []


def test_a_downgrade_is_not_offered() -> None:
    squad = [player(1, "MID", 6.0, cost=50)]
    market = [player(2, "MID", 3.0, cost=50)]
    assert affordable_transfers(squad, market, bank=100, limit=10) == []


def test_each_target_appears_once_against_whoever_it_most_improves() -> None:
    """Otherwise one premium striker fills the list opposite every forward."""
    squad = [player(1, "FWD", 2.0, cost=50), player(2, "FWD", 3.0, cost=50)]
    market = [player(9, "FWD", 9.0, cost=50)]
    transfers = affordable_transfers(squad, market, bank=100, limit=10)
    assert [(t.incoming.id, t.out.id) for t in transfers] == [(9, 1)]


def test_one_squad_player_cannot_monopolise_the_list() -> None:
    """Eight ways to replace the same weak link is one suggestion, not eight."""
    squad = [player(1, "MID", 0.5, cost=40), player(2, "DEF", 4.0, cost=40)]
    market = [player(10 + i, "MID", 8.0 - i * 0.1, cost=40) for i in range(8)]
    market.append(player(30, "DEF", 6.0, cost=40))

    transfers = affordable_transfers(squad, market, bank=100, limit=10)
    assert sum(t.out.id == 1 for t in transfers) == 3
    assert [t.incoming.id for t in transfers if t.out.id == 2] == [30]


def test_the_best_upgrades_come_first() -> None:
    squad = [player(1, "MID", 1.0, cost=40), player(2, "DEF", 1.0, cost=40)]
    market = [player(10, "MID", 4.0, cost=40), player(11, "DEF", 9.0, cost=40)]
    assert [t.incoming.id for t in affordable_transfers(squad, market, bank=100, limit=10)] == [11, 10]


# ── comparing two elevens ───────────────────────────────────────────────


def test_a_captained_total_counts_its_captain_twice() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, starters[1]) == 21.0


def test_an_uncaptained_total_is_the_plain_sum() -> None:
    starters = squad_of(("MID", 5.0), ("FWD", 8.0))
    assert points_with_captain(starters, None) == 13.0


def test_a_ruled_out_captain_adds_nothing() -> None:
    starters = [player(1, "MID", 5.0), player(2, "FWD", 8.0, chance_of_playing=0)]
    assert points_with_captain(starters, starters[1]) == 5.0


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
    assert [t.incoming.id for t in affordable_transfers(squad, market, bank=100, limit=10)] == [2]


# ── free transfers ──────────────────────────────────────────────────────


def _played(event: int, transfers: int = 0) -> GameweekResult:
    return GameweekResult(event=event, points=50, transfers_made=transfers, transfers_cost=0)


def test_one_free_transfer_in_the_opening_gameweek() -> None:
    assert free_transfers([], upcoming=1) == 1


def test_an_unused_transfer_rolls_over() -> None:
    assert free_transfers([_played(1)], upcoming=2) == 2


def test_using_the_allowance_resets_it_to_one() -> None:
    assert free_transfers([_played(1, transfers=1)], upcoming=2) == 1


def test_rollover_is_capped() -> None:
    """Five is the ceiling however long a manager sits on their hands."""
    assert free_transfers([_played(e) for e in range(1, 12)], upcoming=12) == MAX_FREE_TRANSFERS


def test_a_gameweek_of_hits_never_drops_below_one() -> None:
    assert free_transfers([_played(1, transfers=4)], upcoming=2) == 1


def test_a_missing_gameweek_is_skipped_rather_than_assumed() -> None:
    """A manager who joined late has no row for the gameweeks before they started."""
    assert free_transfers([_played(3)], upcoming=4) == 2


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
