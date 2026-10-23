"""Optimal lineup selection.

Deliberately not delegated to the model. "Which legal lineup maximises projected
points" is a constraint-satisfaction problem with an exact answer; asking an LLM
would introduce error into the one part of the football report that has none.
The model's job is judgement — is the projection trustworthy, is the matchup
bad, is the injury real — not arithmetic.
"""

from dataclasses import dataclass

from thefrontoffice.adapters.outbound.platforms.sleeper.types import FLEX_ELIGIBILITY, WeeklyProjection


@dataclass(frozen=True)
class LineupSlot:
    """One filled starting slot."""

    slot: str
    player: WeeklyProjection | None

    @property
    def points(self) -> float:
        return self.player.points if self.player else 0.0


def eligible_positions(slot: str) -> tuple[str, ...]:
    """Which positions may fill `slot`."""
    return FLEX_ELIGIBILITY.get(slot, (slot,))


def optimal_lineup(slots: list[str], players: list[WeeklyProjection]) -> list[LineupSlot]:
    """Assign the highest-projecting legal lineup.

    Slots are filled in order of how restrictive they are — a QB slot before a
    FLEX, a FLEX before a SUPER_FLEX. Filling the loose slots first would let a
    SUPER_FLEX take the only quarterback and leave the QB slot empty, which is
    the classic way a naive greedy assignment goes wrong.
    """
    available = sorted(players, key=lambda p: p.points, reverse=True)
    order = sorted(range(len(slots)), key=lambda i: (len(eligible_positions(slots[i])), i))

    taken: set[str] = set()
    filled: dict[int, LineupSlot] = {}
    for index in order:
        slot = slots[index]
        allowed = eligible_positions(slot)
        pick = next(
            (p for p in available if p.player_id not in taken and p.position in allowed),
            None,
        )
        if pick:
            taken.add(pick.player_id)
        filled[index] = LineupSlot(slot=slot, player=pick)

    return [filled[i] for i in range(len(slots))]


def lineup_points(lineup: list[LineupSlot]) -> float:
    return round(sum(s.points for s in lineup), 2)


@dataclass(frozen=True)
class LineupChange:
    """A player who should come into the lineup, and who they displace."""

    slot: str
    start: WeeklyProjection
    bench: WeeklyProjection | None

    @property
    def gain(self) -> float:
        return round(self.start.points - (self.bench.points if self.bench else 0.0), 2)


def lineup_changes(
    slots: list[str], current_starter_ids: list[str], players: list[WeeklyProjection]
) -> list[LineupChange]:
    """What to change to reach the optimal lineup, as swaps that can each be made, best gain first.

    Compares by player rather than by slot: shuffling the same players between a
    RB and a FLEX slot is not a start/sit decision and should not be reported as
    one. Each player coming in is paired with one going out only where that swap
    alone leaves a legal lineup — pairing by points instead once told a manager
    to start a running back over his only tight end, which no platform allows,
    and hid the tight-end swap the change actually needed.
    """
    best = optimal_lineup(slots, players)
    best_ids = {s.player.player_id for s in best if s.player}
    current_ids = set(current_starter_ids)
    by_id = {p.player_id: p for p in players}

    lineup = [by_id[pid] for pid in current_starter_ids if pid in by_id]
    coming_in = sorted((s for s in best if s.player and s.player.player_id not in current_ids), key=lambda s: -s.points)
    going_out = sorted((by_id[pid] for pid in current_ids - best_ids if pid in by_id), key=lambda p: p.points)

    changes = []
    for slot in coming_in:
        assert slot.player is not None
        out = next((p for p in going_out if fits(slots, [q for q in lineup if q is not p] + [slot.player])), None)
        if out is None and not fits(slots, [*lineup, slot.player]):
            # No single swap brings him in; the change needs several at once,
            # which the page cannot phrase as one row. Rare, and left out
            # rather than shown as a swap that cannot be made.
            continue
        if out is not None:
            going_out.remove(out)
            lineup = [q for q in lineup if q is not out]
        lineup.append(slot.player)
        changes.append(LineupChange(slot=slot.slot, start=slot.player, bench=out))
    # A swap that loses points is not a recommendation. It arises when a slot
    # holds someone ineligible for it, making the replacement forced rather than
    # an upgrade.
    return sorted((c for c in changes if c.gain > 0), key=lambda c: c.gain, reverse=True)


def current_lineup(slots: list[str], starter_ids: list[str], players: list[WeeklyProjection]) -> list[LineupSlot]:
    """The lineup as it stands.

    Sleeper's `starters` array is positional: entry i is whoever occupies slot i
    of `roster_positions`. An empty slot is the literal id "0".
    """
    by_id = {p.player_id: p for p in players}
    filled = []
    for i, slot in enumerate(slots):
        player = by_id.get(starter_ids[i]) if i < len(starter_ids) else None
        # Sleeper will not let an ineligible player occupy a slot, but a stale
        # or hand-built roster can; showing it would misstate the lineup total.
        if player and player.position not in eligible_positions(slot):
            player = None
        filled.append(LineupSlot(slot=slot, player=player))
    return filled


def best_upgrade(lineup: list[LineupSlot], candidate: WeeklyProjection) -> tuple[float, LineupSlot] | None:
    """What `candidate` would add starting in place of the weakest starter he can replace.

    The slot he can fill with the least in it, and how much more he projects
    than whoever — or nobody — is there. None where he can fill no slot.
    Projections only: this ranks a list, and the judgment of whether to act
    on it is the model's, made with the role and the matchup beside it.
    """
    eligible = [slot for slot in lineup if candidate.position in eligible_positions(slot.slot)]
    if not eligible:
        return None
    weakest = min(eligible, key=lambda slot: slot.points)
    return round(candidate.points - weakest.points, 2), weakest


def fits(slots: list[str], players: list[WeeklyProjection]) -> bool:
    """Whether `players` can fill `slots` legally, each in a slot his position allows.

    Exact rather than greedy: a set of starters is legal if *any* assignment
    works, and a swap that slides a flex player into a vacated slot is the
    common case a slot-by-slot check misses. Lineups are a dozen slots, so
    trying assignments in the order of the most restrictive slot is instant.
    """
    if len(players) > len(slots):
        return False
    order = sorted(range(len(slots)), key=lambda i: len(eligible_positions(slots[i])))
    remaining = list(players)

    def place(at: int) -> bool:
        if not remaining:
            return True
        if at == len(order):
            return False
        slot = slots[order[at]]
        for i, player in enumerate(remaining):
            if player.position in eligible_positions(slot):
                remaining.pop(i)
                if place(at + 1):
                    return True
                remaining.insert(i, player)
        # Or leave this slot empty, where there are more slots than players.
        return len(remaining) < len(order) - at and place(at + 1)

    return place(0)
