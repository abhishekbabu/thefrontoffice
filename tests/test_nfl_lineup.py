"""Tests for optimal lineup selection.

This is the one part of the football report with an exact answer, so it is
computed rather than asked of the model — and therefore worth pinning hard.
"""

from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    LineupSlot,
    best_upgrade,
    eligible_positions,
    fits,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import WeeklyProjection


def p(pid: str, pos: str, pts: float, name: str = "") -> WeeklyProjection:
    return WeeklyProjection(
        player_id=pid, name=name or f"{pos} {pid}", position=pos, team="BUF", opponent="MIA", points=pts
    )


def _names(lineup: list[LineupSlot]) -> list[str]:
    return [s.player.player_id if s.player else "-" for s in lineup]


# ── slot eligibility ────────────────────────────────────────────────────


def test_a_named_slot_accepts_only_that_position() -> None:
    assert eligible_positions("QB") == ("QB",)
    assert eligible_positions("TE") == ("TE",)


def test_flex_variants_have_the_right_eligibility() -> None:
    assert set(eligible_positions("FLEX")) == {"RB", "WR", "TE"}
    assert set(eligible_positions("WRRB_FLEX")) == {"RB", "WR"}
    assert set(eligible_positions("SUPER_FLEX")) == {"QB", "RB", "WR", "TE"}


# ── optimal_lineup ──────────────────────────────────────────────────────


def test_each_slot_takes_the_best_eligible_player() -> None:
    players = [p("qb1", "QB", 20), p("qb2", "QB", 12), p("rb1", "RB", 15), p("rb2", "RB", 9)]
    assert _names(optimal_lineup(["QB", "RB"], players)) == ["qb1", "rb1"]


def test_a_player_cannot_fill_two_slots() -> None:
    players = [p("rb1", "RB", 20), p("rb2", "RB", 8)]
    assert _names(optimal_lineup(["RB", "RB"], players)) == ["rb1", "rb2"]


def test_flex_takes_the_best_leftover_across_positions() -> None:
    players = [p("rb1", "RB", 20), p("rb2", "RB", 6), p("wr1", "WR", 18), p("te1", "TE", 14)]
    lineup = optimal_lineup(["RB", "WR", "FLEX"], players)
    assert _names(lineup) == ["rb1", "wr1", "te1"]  # TE 14 beats RB2 6


def test_superflex_does_not_steal_the_only_quarterback() -> None:
    """The classic greedy failure: fill SUPER_FLEX first with the top scorer and
    the QB slot is left empty."""
    players = [p("qb1", "QB", 25), p("rb1", "RB", 20), p("rb2", "RB", 12)]
    lineup = optimal_lineup(["QB", "SUPER_FLEX"], players)
    assert _names(lineup) == ["qb1", "rb1"]
    assert lineup_points(lineup) == 45.0


def test_a_slot_with_nobody_eligible_is_left_empty() -> None:
    players = [p("rb1", "RB", 20)]
    lineup = optimal_lineup(["QB", "RB"], players)
    assert lineup[0].player is None
    assert lineup[0].points == 0.0
    assert lineup_points(lineup) == 20.0


def test_empty_roster_yields_empty_slots() -> None:
    lineup = optimal_lineup(["QB", "RB", "FLEX"], [])
    assert all(s.player is None for s in lineup)
    assert lineup_points(lineup) == 0.0


def test_slot_order_is_preserved_in_the_result() -> None:
    """The optimiser fills restrictive slots first, but must return them in the
    league's own order so the rendered lineup reads correctly."""
    players = [p("qb1", "QB", 25), p("rb1", "RB", 20), p("wr1", "WR", 18)]
    lineup = optimal_lineup(["FLEX", "QB", "RB"], players)
    assert [s.slot for s in lineup] == ["FLEX", "QB", "RB"]


def test_defense_and_kicker_slots_are_filled() -> None:
    players = [p("k1", "K", 9), p("d1", "DEF", 7)]
    assert _names(optimal_lineup(["K", "DEF"], players)) == ["k1", "d1"]


# ── lineup_changes ──────────────────────────────────────────────────────


def test_no_changes_when_the_lineup_is_already_optimal() -> None:
    players = [p("rb1", "RB", 20), p("rb2", "RB", 8)]
    assert lineup_changes(["RB"], ["rb1"], players) == []


def test_a_better_bench_player_is_surfaced_with_the_gain() -> None:
    players = [p("rb1", "RB", 20), p("rb2", "RB", 8)]
    changes = lineup_changes(["RB"], ["rb2"], players)
    assert len(changes) == 1
    assert changes[0].start.player_id == "rb1"
    assert changes[0].bench is not None
    assert changes[0].bench.player_id == "rb2"
    assert changes[0].gain == 12.0


def test_changes_are_ordered_by_gain() -> None:
    players = [
        p("rb1", "RB", 20),
        p("rb2", "RB", 5),
        p("wr1", "WR", 14),
        p("wr2", "WR", 12),
    ]
    changes = lineup_changes(["RB", "WR"], ["rb2", "wr2"], players)
    assert [c.start.player_id for c in changes] == ["rb1", "wr1"]
    assert changes[0].gain > changes[1].gain


def test_shuffling_the_same_players_between_slots_is_not_a_change() -> None:
    """Moving a RB from the RB slot to FLEX is not a start/sit decision."""
    players = [p("rb1", "RB", 20), p("wr1", "WR", 18)]
    assert lineup_changes(["RB", "FLEX"], ["rb1", "wr1"], players) == []


def test_filling_an_empty_slot_reports_no_benched_player() -> None:
    players = [p("rb1", "RB", 20), p("rb2", "RB", 10)]
    changes = lineup_changes(["RB", "RB"], ["rb1"], players)
    assert len(changes) == 1
    assert changes[0].start.player_id == "rb2"
    assert changes[0].bench is None
    assert changes[0].gain == 10.0


# ── current_lineup ──────────────────────────────────────────────────────


def test_current_lineup_is_positional() -> None:
    """Sleeper's `starters` array maps 1:1 onto roster_positions."""
    from thefrontoffice.adapters.outbound.competitions.nfl.lineup import current_lineup

    players = [p("qb1", "QB", 22), p("rb1", "RB", 18)]
    lineup = current_lineup(["QB", "RB"], ["qb1", "rb1"], players)
    assert _names(lineup) == ["qb1", "rb1"]


def test_an_unfilled_starter_slot_is_empty() -> None:
    from thefrontoffice.adapters.outbound.competitions.nfl.lineup import current_lineup

    players = [p("qb1", "QB", 22)]
    lineup = current_lineup(["QB", "RB"], ["qb1"], players)
    assert lineup[1].player is None


def test_an_ineligible_player_does_not_count_toward_the_slot() -> None:
    """A stale roster could put a QB in a WR slot; counting it would overstate
    the lineup total and make every swap look like a downgrade."""
    from thefrontoffice.adapters.outbound.competitions.nfl.lineup import current_lineup

    players = [p("qb1", "QB", 22)]
    lineup = current_lineup(["WR"], ["qb1"], players)
    assert lineup[0].player is None
    assert lineup_points(lineup) == 0.0


def test_a_swap_that_loses_points_is_not_recommended() -> None:
    """Forced replacements are not upgrades, and '+-2.4' is worse than silence."""
    players = [p("qb1", "QB", 22), p("wr1", "WR", 10)]
    changes = lineup_changes(["WR"], ["qb1"], players)
    assert all(c.gain > 0 for c in changes)


# ── how a candidate fits ────────────────────────────────────────────────


def test_a_candidate_is_measured_against_the_weakest_starter_he_could_replace() -> None:
    lineup = [
        LineupSlot(slot="RB", player=p("r1", "RB", 20.0)),
        LineupSlot(slot="WR", player=p("w1", "WR", 9.0)),
        LineupSlot(slot="FLEX", player=p("r2", "RB", 11.0)),
    ]

    upgrade = best_upgrade(lineup, p("fa", "RB", 14.0))

    # The RB slot holds 20 and FLEX 11; he would replace the FLEX.
    assert upgrade is not None
    gain, slot = upgrade
    assert (gain, slot.slot) == (3.0, "FLEX")


def test_an_empty_slot_he_can_fill_is_worth_his_whole_projection() -> None:
    upgrade = best_upgrade([LineupSlot(slot="TE", player=None)], p("fa", "TE", 7.5))

    assert upgrade is not None and upgrade[0] == 7.5


def test_a_candidate_no_slot_takes_does_not_fit() -> None:
    assert best_upgrade([LineupSlot(slot="QB", player=p("q", "QB", 20.0))], p("fa", "K", 9.0)) is None


# ── whether a set of starters is legal ──────────────────────────────────


def test_a_set_of_starters_fits_when_any_assignment_works() -> None:
    """An RB can replace a WR when the flex slides across to cover the WR slot."""
    slots = ["RB", "WR", "FLEX"]

    assert fits(slots, [p("r1", "RB", 1), p("r2", "RB", 1), p("w1", "WR", 1)])
    assert fits(slots, [p("r1", "RB", 1), p("w1", "WR", 1), p("w2", "WR", 1)])


def test_a_set_of_starters_that_no_assignment_fits_does_not() -> None:
    assert not fits(["RB", "WR", "FLEX"], [p("r1", "RB", 1), p("r2", "RB", 1), p("r3", "RB", 1)])
    assert not fits(["QB"], [p("w1", "WR", 1)])


def test_a_lineup_may_leave_a_slot_empty_but_not_overflow() -> None:
    assert fits(["QB", "RB"], [p("q", "QB", 1)])
    assert not fits(["QB"], [p("q", "QB", 1), p("q2", "QB", 1)])


def test_a_change_is_never_a_swap_that_leaves_a_slot_unfillable() -> None:
    """The best lineup swaps the tight end and moves the flex: pairing by points alone
    said to start the running back over the only tight end, which no platform allows."""
    slots = ["RB", "WR", "TE", "FLEX"]
    players = [
        p("rb1", "RB", 20),
        p("wr1", "WR", 11),
        p("te1", "TE", 8),
        p("flex", "WR", 12),
        p("rb2", "RB", 14),
        p("te2", "TE", 10),
    ]

    changes = lineup_changes(slots, ["rb1", "wr1", "te1", "flex"], players)

    for change in changes:
        lineup = [q for q in players if q.player_id in {"rb1", "wr1", "te1", "flex"}]
        out = {change.bench.player_id} if change.bench else set()
        assert fits(slots, [q for q in lineup if q.player_id not in out] + [change.start])
    assert {(c.start.player_id, c.bench.player_id if c.bench else None) for c in changes} == {
        ("rb2", "wr1"),
        ("te2", "te1"),
    }
