"""What an FPL gameweek asks of the manager, as a list of things to do.

Every item is weighed on one figure, a player's worth (`worth.Valuation`): the
gameweek's for the eleven and the armband, the next `worth.HORIZON` gameweeks'
for a transfer, since a player bought is kept for weeks. Five kinds:

- a starter swapped for a bench player, first where the starter is flagged or
  his club blanks;
- the armband, when the best captain or vice is not the one set;
- the bench reordered, when the first substitute will not play;
- transfers that fit the bank and the free transfers, a hit only when it clears
  its four points by a margin;
- a chip about to expire unplayed, with when to play it where a double or a
  blank is coming.

Margins keep the list to moves worth making: a projection cannot settle a
tenth of a point, and every transfer spends something kept for later.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    TRANSFER_HIT,
    Lineup,
    Roster,
    Transfer,
    affordable_transfers,
    club_counts,
    likely,
    lineup_changes,
    room_at,
)
from thefrontoffice.adapters.outbound.competitions.premier_league.views import fixture_text
from thefrontoffice.adapters.outbound.competitions.premier_league.worth import HORIZON, Valuation
from thefrontoffice.adapters.outbound.platforms.fpl.types import Chip, ChipPlay, Fixture, Gameweek, Player, as_millions
from thefrontoffice.domain.models import Action, Held, MovePlayer, MoveSide, Stat

LINEUP_MARGIN = 0.5
"""Points of worth a bench player must add over the starter he replaces, unless that starter is
flagged or blanks: half a point, below which the swap is a coin flip and the eleven as set stands."""

ARMBAND_MARGIN = 0.5
"""Points of worth the best captain must have over the one set before the armband moves — doubled,
a point on the gameweek — unless the one set is unlikely to play."""

TRANSFER_MARGIN = 1.5
"""Points over the horizon a free transfer must gain: a free transfer banked is worth one later,
so a swap of near equals is left alone."""

HIT_MARGIN = 2.0
"""Points over the horizon a transfer beyond the free ones must gain on top of its four-point hit:
a hit is certain and the gain is a projection, so it has to clear by more than the cost."""

TRANSFERS = 3
"""Transfers named at once: the clearest few, not a rebuild a Wildcard is for."""

HITS = 1
"""Hits named at once: one taken for a clear gain is a decision; two is a rebuild."""

CHIP_NOTICE = 3
"""Gameweeks before a chip's window closes that it becomes a to-do: enough to plan around a double or a blank."""

# Which chips a double gameweek or a blank one makes the time for. A Wildcard rebuilds for weeks
# and keys to neither.
DOUBLE_CHIPS = frozenset({"bboost", "3xc", "freehit"})
BLANK_CHIPS = frozenset({"freehit"})

NO_FIGURE = "—"
WORTH = "Worth"
"""What he adds the gameweek being decided (`worth.Worth.week`)."""


@dataclass(frozen=True)
class Plan:
    """What the gameweek to come is decided on: the squad, every player's worth, and what can be spent."""

    roster: Roster
    value: Valuation
    upcoming: Gameweek
    allowance: int
    selling: Mapping[int, int]
    market: Sequence[Player]
    chips: Sequence[Chip] = ()
    played: Sequence[ChipPlay] = ()


def build(plan: Plan, best: Lineup) -> list[Action]:
    """Every decision the gameweek asks for: lineup first, then the armband, the bench, transfers and chips."""
    when = deadline(plan.upcoming)
    items = starts(plan, best, when)
    items += armband(plan, best, when)
    moved = {pid for item in items for pid in (item.player_id, item.replaces) if pid}
    items += bench(plan, moved, when)
    fixed = {item.replaces for item in items if item.kind == "lineup" and item.replaces}
    items += transfers(plan, best, fixed, when)
    items += chips(plan)
    return items


def deadline(upcoming: Gameweek) -> str:
    return f"GW{upcoming.id} deadline, {at_time(upcoming.deadline)} UTC"


def blanks(plan: Plan, player: Player) -> bool:
    """Whether his club has no match in the gameweek being decided."""
    found = plan.value.of(player)
    return found is not None and not found.fixtures


def trouble(plan: Plan, player: Player) -> str:
    """Why a starter will score nothing or may not play — 'blanks GW11', 'doubt 50%' — or empty when he will."""
    if blanks(plan, player):
        return f"blanks GW{plan.upcoming.id}"
    if not likely(player):
        return player.availability or "ruled out"
    return ""


# ── the eleven ──────────────────────────────────────────────────────


def starts(plan: Plan, best: Lineup, when: str) -> list[Action]:
    """Each change from the eleven as set to the best one, where it gains `LINEUP_MARGIN` or saves a starter in trouble.

    Any subset of the changes leaves a legal eleven (`rules.lineup_changes`), so
    leaving out the small ones never strands the big ones.
    """
    items = []
    for change in lineup_changes(plan.roster.starters, best, plan.value):
        drop = change.drop
        problem = trouble(plan, drop) if drop else ""
        if not problem and change.gain < LINEUP_MARGIN:
            continue
        start = change.start
        reason = f"+{change.gain:.1f} pts this gameweek."
        if drop is not None and problem:
            reason = f"{drop.name}: {problem}. {reason}"
        items.append(
            Action(
                kind="lineup",
                urgency="now" if problem else "soon",
                title=f"Start {start.name} over {drop.name}" if drop else f"Start {start.name}",
                reason=reason,
                when=when,
                player_id=str(start.id),
                replaces=str(drop.id) if drop else "",
                players=compared(plan, [("in", "bench", start), *([("out", "starter", drop)] if drop else [])]),
                key=f"start:{start.id}:{drop.id if drop else ''}",
            )
        )
    return items


def armband(plan: Plan, best: Lineup, when: str) -> list[Action]:
    """The best captain and vice, where they are not the ones set (`ARMBAND_MARGIN`).

    The captain is the starter worth most who is likely to play (`rules.armbands`),
    and the vice the next: the vice scores double only when the captain does not
    play, so he has to be somebody who will.
    """
    captain, vice = best.captain, best.vice
    current, current_vice = plan.roster.captain, plan.roster.vice
    if captain is None:
        return []
    starting = {p.id for p in best.starters}
    gain = plan.value(captain) - (plan.value(current) if current and current.id in starting else 0.0)
    move_captain = current is None or (
        current.id != captain.id and (gain >= ARMBAND_MARGIN or not likely(current) or current.id not in starting)
    )
    move_vice = vice is not None and (
        current_vice is None
        or (current_vice.id != vice.id and (not likely(current_vice) or current_vice.id not in starting))
    )
    if not move_captain and not move_vice:
        return []
    if move_captain:
        title = f"Captain {captain.name}" + (f", vice {vice.name}" if vice else "")
    else:
        title = f"Vice-captain {vice.name}" if vice else ""
    doubled = plan.value(captain) * 2
    reason = f"{captain.name} {plan.value(captain):.1f} × 2 = {doubled:.1f} pts."
    if move_captain and current is not None and current.id != captain.id:
        problem = trouble(plan, current)
        against = f"{current.name}: {problem}." if problem else f"{current.name} {plan.value(current) * 2:.1f}."
        reason = f"{reason} {against}"
    moved: list[tuple[MoveSide, Held, Player]] = [("in", "starter", captain)]
    if vice is not None:
        moved.append(("in", "starter", vice))
    if move_captain and current is not None and current.id != captain.id:
        moved.append(("out", "starter", current))
    return [
        Action(
            kind="lineup",
            urgency="now" if current is None or not likely(current) else "soon",
            title=title,
            reason=reason,
            when=when,
            player_id=str(captain.id),
            players=compared(plan, moved),
            key=f"armband:{captain.id}:{vice.id if vice else ''}",
        )
    ]


def bench(plan: Plan, moved: set[str], when: str) -> list[Action]:
    """The first outfield substitute up the order, where the one there will not play and one behind him will.

    Auto-subs come on in bench order, so a first substitute who is out or blanks
    hands a starter's no-show to nobody. Players another item already moves are
    left to it.
    """
    outfield = [p for p in plan.roster.bench if p.position != "GKP" and str(p.id) not in moved]
    if len(outfield) < 2 or not trouble(plan, outfield[0]):
        return []
    first = outfield[0]
    behind = [p for p in outfield[1:] if not trouble(plan, p)]
    if not behind:
        return []
    up = max(behind, key=plan.value)
    return [
        Action(
            kind="lineup",
            urgency="soon",
            title=f"Move {up.name} to first sub, ahead of {first.name}",
            reason=f"{first.name}: {trouble(plan, first)}. Auto-subs come on in bench order.",
            when=when,
            player_id=str(up.id),
            replaces=str(first.id),
            players=compared(plan, [("in", "bench", up), ("out", "bench", first)]),
            key=f"bench:{up.id}:{first.id}",
        )
    ]


# ── the squad ───────────────────────────────────────────────────────


def transfers(plan: Plan, best: Lineup, fixed: set[str], when: str) -> list[Action]:
    """The transfers worth making, within the bank and the free transfers, best gain over the horizon first.

    A starter in trouble whom no bench swap covers is transferred out first,
    and urgently. Each transfer after the free ones costs `TRANSFER_HIT` and is
    named only when it gains that plus `HIT_MARGIN`, and only for a player in
    the best eleven: a bench player's gain is points he scores only if somebody
    else does not play, which no certain four points is worth. At most `HITS`
    of them, and `TRANSFERS` in all. Money and club places carry from one to the next.
    """
    squad = plan.roster.players
    bank = plan.roster.squad.bank
    options = affordable_transfers(
        squad, list(plan.market), bank, selling=dict(plan.selling), limit=len(plan.market), value=plan.value.horizon
    )
    starters = {p.id for p in plan.roster.starters}
    eleven = {p.id for p in best.starters}

    def urgent(transfer: Transfer) -> bool:
        out = transfer.out
        return out.id in starters and str(out.id) not in fixed and bool(trouble(plan, out))

    options.sort(key=lambda t: (not urgent(t), -t.gain))
    clubs = club_counts(squad)
    used: set[int] = set()
    items: list[Action] = []
    hits = 0
    for transfer in options:
        if len(items) == TRANSFERS:
            break
        out, incoming = transfer.out, transfer.incoming
        if out.id in used or incoming.id in used or transfer.cost > bank or not room_at(clubs, incoming, out):
            continue
        free = len(items) < plan.allowance
        if transfer.gain < (TRANSFER_MARGIN if free else TRANSFER_HIT + HIT_MARGIN):
            continue
        if not free and (hits == HITS or out.id not in eleven):
            continue
        bank -= transfer.cost
        used |= {out.id, incoming.id}
        clubs[out.team] -= 1
        clubs[incoming.team] = clubs.get(incoming.team, 0) + 1
        hits += not free
        items.append(_transfer_item(plan, transfer, bank, free=free, urgent=urgent(transfer), when=when))
    return items


def _transfer_item(plan: Plan, transfer: Transfer, bank: int, *, free: bool, urgent: bool, when: str) -> Action:
    out, incoming = transfer.out, transfer.incoming
    span = f"GW{plan.upcoming.id}-{plan.upcoming.id + HORIZON - 1}"
    price = (
        f"{'Costs' if transfer.cost > 0 else 'Frees'} {as_millions(abs(transfer.cost))}" if transfer.cost else "No cost"
    )
    money = f"{price}, {as_millions(bank)} left."
    cost = "Free transfer." if free else f"−{TRANSFER_HIT} hit: +{transfer.gain - TRANSFER_HIT:.1f} net."
    problem = trouble(plan, out) if urgent else ""
    reason = f"+{transfer.gain:.1f} pts over {span}. {cost} {money}"
    if problem:
        reason = f"{out.name}: {problem}. {reason}"
    return Action(
        kind="transfer",
        urgency="now" if urgent else "soon",
        title=f"Transfer in {incoming.name} for {out.name}",
        reason=reason,
        when=when,
        player_id=str(incoming.id),
        drop=str(out.id),
        players=compared(
            plan,
            [("in", "market", incoming), ("out", _held(plan, out), out)],
            prices={incoming.id: incoming.cost, out.id: transfer.sale},
        ),
        key=f"transfer:{incoming.id}:{out.id}",
    )


def _held(plan: Plan, player: Player) -> Held:
    return "starter" if any(p.id == player.id for p in plan.roster.starters) else "bench"


# ── chips ───────────────────────────────────────────────────────────


def chips(plan: Plan) -> list[Action]:
    """Each chip whose window closes within `CHIP_NOTICE` gameweeks unplayed, and when to play it where the fixtures say.

    A first-half chip not played by its last gameweek is lost, not carried, so
    the reminder comes while there are still weeks to choose between. The hint
    names a double or a blank for the squad's clubs inside the window, and only
    for a chip it is the time for; with none coming, the item says only when it goes.
    """
    week = plan.upcoming.id
    items = []
    for chip in plan.chips:
        if not chip.covers(week) or chip.stop_event - week >= CHIP_NOTICE:
            continue
        if any(chip.covers(p.event) and p.name == chip.name for p in plan.played):
            continue
        hint = _timing(plan, chip)
        items.append(
            Action(
                kind="chip",
                urgency="now" if chip.stop_event == week else "soon",
                title=f"Play {chip.label} by GW{chip.stop_event}",
                reason=f"Lost unplayed after the GW{chip.stop_event} deadline." + (f" {hint}" if hint else ""),
                when=f"GW{chip.stop_event}",
                key=f"chip:{chip.name}:{chip.stop_event}",
            )
        )
    return items


def _timing(plan: Plan, chip: Chip) -> str:
    """'GW13: double for ARS, MCI.' — the first double or blank for the squad's clubs in the chip's window it suits."""
    clubs = sorted({p.team for p in plan.roster.players})
    for week, fixtures in plan.value.weeks.items():
        if not chip.covers(week):
            continue
        counts = _matches(fixtures)
        doubles = [c for c in clubs if counts.get(c, 0) > 1]
        blanked = [c for c in clubs if counts.get(c, 0) == 0] if fixtures else []
        if doubles and chip.name in DOUBLE_CHIPS:
            return f"GW{week}: double for {', '.join(doubles)}."
        if blanked and chip.name in BLANK_CHIPS:
            return f"GW{week}: blank for {', '.join(blanked)}."
    return ""


def _matches(fixtures: Sequence[Fixture]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fixture in fixtures:
        for club in (fixture.home, fixture.away):
            counts[club] = counts.get(club, 0) + 1
    return counts


# ── figures ─────────────────────────────────────────────────────────


def compared(
    plan: Plan, moved: Sequence[tuple[MoveSide, Held, Player]], prices: Mapping[int, int] | None = None
) -> list[MovePlayer]:
    """The players an item moves, each on the same rows (`figures`), for reading side by side."""
    return [
        MovePlayer(
            side=side,
            player_id=str(player.id),
            name=player.name,
            position=player.position,
            team=player.team,
            held=held,
            figures=figures(plan, player, prices),
        )
        for side, held, player in moved
    ]


def figures(plan: Plan, player: Player, prices: Mapping[int, int] | None = None) -> list[Stat]:
    """His worth this gameweek and over the horizon, his form, his fixture and his status — and with
    `prices`, what he costs or sells for — alike for every player on an item."""
    found = plan.value.of(player)
    rows = [
        Stat(label=WORTH, value=f"{found.week:.1f}" if found else NO_FIGURE),
        Stat(label=f"Next {HORIZON}", value=f"{found.horizon:.1f}" if found else NO_FIGURE),
        Stat(label="Pts/match", value=f"{found.form:.1f}" if found and found.form is not None else NO_FIGURE),
        Stat(label="Fixture", value=fixture_text(list(found.fixtures)) if found else NO_FIGURE),
        Stat(label="Status", value=player.availability or "fit", tone="warning" if player.availability else "neutral"),
    ]
    if prices is not None:
        rows.append(Stat(label="Price", value=as_millions(prices.get(player.id, player.cost))))
    return rows
