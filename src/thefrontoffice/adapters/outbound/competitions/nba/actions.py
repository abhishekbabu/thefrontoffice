"""What a basketball week asks of the manager, as a list of things to do.

Every item is weighed on one figure, a player's worth this week
(`worth.Reading.worth`: a game's value × minutes nudge × games left), so the
list, the lineup rows and the prompt agree. Three kinds besides the IL move
(`week.off_il`): a bench player to start over a starter, a free agent to stream
in for the weakest player you could drop, and that drop.

Yahoo sets a basketball lineup day by day, and none of this sees a day: a start
is the player with more games or more value this week, which can still be the
wrong call on a night only the other one plays. Its reason says so.
"""

from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.nba import views
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, fits, ruled_out
from thefrontoffice.adapters.outbound.competitions.nba.week import BENCH, off_il
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import Action, Held

MARGIN = 0.2
"""How much more a player must be worth this week than the one he would replace: a fifth.

Below that a move is a coin flip a projection cannot settle, and every add
spends one of the week's few, so the list names only the clear ones.
"""

STARTS = 3
"""Start-over items at once: the clearest few, not every reshuffle the bench allows."""

STREAMS = 2
"""Pickups at once, and never more than the adds left."""

KEPT = 0.5
"""The share of your roster never offered as a drop: the better half by value a game.

Worth this week is a week's figure, and a star with one game left reads low on
it; what a player gives a game says whether he is one to keep at all.
"""


def build(
    roster: Sequence[YahooPlayer],
    free_agents: Sequence[YahooPlayer],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
) -> list[Action]:
    """Every decision the week asks for: IL moves first, then starts, then pickups each with its drop."""
    items = off_il(list(roster))
    items += starts(roster, readings, by_points)
    named = {pid for item in items for pid in (item.player_id, item.replaces) if pid}
    items += streams(roster, free_agents, readings, adds_left, by_points, named)
    return items


def beats(theirs: float, mine: float) -> bool:
    """Whether `theirs` is worth more than `mine` by `MARGIN` of it; any worth beats nought."""
    return theirs > mine + abs(mine) * MARGIN and theirs > mine


def held(player: YahooPlayer) -> Held:
    """Where he stands to you: in the lineup, on the bench, in an injured slot, or on the wire."""
    if not player.slot:
        return "free agent"
    if player.slot in INJURED_SLOTS:
        return "reserve"
    return "bench" if player.slot == BENCH else "starter"


def _unit(by_points: bool) -> str:
    return "fpts" if by_points else "value"


def starts(roster: Sequence[YahooPlayer], readings: Mapping[str, Reading], by_points: bool) -> list[Action]:
    """Bench players worth more this week than a starter whose slot they can fill, best gain first.

    Each starter is named once, against the weakest he could replace, and only
    a bench player Yahoo lets into that slot (`rules.fits`).
    """
    lineup = [r for p in roster if held(p) == "starter" and (r := readings.get(p.player_key)) and r.worth is not None]
    bench = [r for p in roster if held(p) == "bench" and (r := readings.get(p.player_key)) and r.worth is not None]
    pairs = []
    for candidate in bench:
        for starter in lineup:
            if fits(starter.player.slot, candidate.player.position) and beats(_worth(candidate), _worth(starter)):
                pairs.append((_worth(candidate) - _worth(starter), candidate, starter))
    pairs.sort(key=lambda pair: -pair[0])
    taken: set[str] = set()
    items = []
    for gain, candidate, starter in pairs:
        if len(items) == STARTS:
            break
        if candidate.player.player_key in taken or starter.player.player_key in taken:
            continue
        taken |= {candidate.player.player_key, starter.player.player_key}
        slot = starter.player.slot
        items.append(
            Action(
                kind="lineup",
                urgency="soon",
                title=f"Start {candidate.player.name} over {starter.player.name}",
                reason=(
                    f"+{gain:.1f} {_unit(by_points)} this week at {slot}. "
                    "Lineups are daily: on a night only one plays, start that one." + _pending(candidate)
                ),
                player_id=candidate.player.player_key,
                replaces=starter.player.player_key,
                players=views.compared(
                    [("in", "bench", candidate), ("out", "starter", starter)],
                    by_points,
                ),
                key=f"start:{candidate.player.player_key}:{starter.player.player_key}",
            )
        )
    return items


def droppable(roster: Sequence[YahooPlayer], readings: Mapping[str, Reading], keep: set[str]) -> list[Reading]:
    """Who you could let go, least worth this week first.

    Never a player in an injured slot — dropping him frees no active spot —
    nor one in the better `KEPT` of the roster by value a game, nor one
    another item already moves, nor one with nothing to read him by: an
    unknown is not a weak player.
    """
    active = [
        r
        for p in roster
        if p.slot not in INJURED_SLOTS and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    ranked = sorted(active, key=lambda r: -_game(r))
    kept = {r.player.player_key for r in ranked[: round(len(ranked) * KEPT)]}
    open_to = [r for r in active if r.player.player_key not in kept | keep and r.worth is not None]
    return sorted(open_to, key=_worth)


def streams(
    roster: Sequence[YahooPlayer],
    free_agents: Sequence[YahooPlayer],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
    named: set[str],
) -> list[Action]:
    """Free agents worth more this week than a player you could drop, each paired with the weakest such drop.

    Best free agent first, each against the weakest drop left that he beats by
    `MARGIN` this week (`droppable`) — and is not worse than by `MARGIN` a game:
    a stream is one week's games, and the player let go is gone for good. Never
    a free agent ruled out: a return date is an estimate, and a stream is games
    now. Never more than `STREAMS`, nor than the adds left — with none left
    there is nothing to stream.
    """
    if adds_left <= 0:
        return []
    owned = {p.player_key for p in roster}
    wire = sorted(
        (
            r
            for p in free_agents
            if p.player_key not in owned
            and not ruled_out(p.status)
            and (r := readings.get(p.player_key))
            and r.worth is not None
        ),
        key=lambda r: -_worth(r),
    )
    drops = droppable(roster, readings, named)
    items = []
    for pickup in wire:
        if len(items) == min(STREAMS, adds_left):
            break
        drop = next((d for d in drops if streams_over(pickup, d)), None)
        if drop is None:
            continue
        drops.remove(drop)
        gain = _worth(pickup) - _worth(drop)
        items.append(
            Action(
                kind="waiver",
                urgency="soon",
                title=f"Pick up {pickup.player.name}, drop {drop.player.name}",
                reason=(
                    f"+{gain:.1f} {_unit(by_points)} this week. {drop.player.name}: weakest you can drop."
                    + _pending(pickup)
                ),
                player_id=pickup.player.player_key,
                drop=drop.player.player_key,
                players=views.compared(
                    [("in", "free agent", pickup), ("out", held(drop.player), drop)],
                    by_points,
                ),
                key=f"stream:{pickup.player.player_key}:{drop.player.player_key}",
            )
        )
    return items


def fit(pickup: Reading, roster: Sequence[YahooPlayer], readings: Mapping[str, Reading], by_points: bool) -> str:
    """'streams over Kel'el Ware: +12.3 value this week (4G vs 2G)'; empty where he clears no drop.

    The weakest player the to-do list would let go (`droppable`) whom he beats
    by `MARGIN` (`streams_over`): what a stream of him would cost, read the
    way the list reads its own pickups.
    """
    drop = next((d for d in droppable(roster, readings, set()) if streams_over(pickup, d)), None)
    if drop is None:
        return ""
    gain = _worth(pickup) - _worth(drop)
    return (
        f"streams over {drop.player.name}: +{gain:.1f} {_unit(by_points)} this week ({pickup.games}G vs {drop.games}G)"
    )


def streams_over(pickup: Reading, drop: Reading) -> bool:
    """Whether `pickup` beats `drop` this week, without giving up more than `MARGIN` of a game for it."""
    return beats(_worth(pickup), _worth(drop)) and _game(pickup) >= _game(drop) - abs(_game(drop)) * MARGIN


PROVISIONAL = " Provisional: schedule not final."
"""What an item weighed on games left adds while the NBA has days of the week to schedule."""


def _pending(reading: Reading) -> str:
    return PROVISIONAL if reading.provisional else ""


def _worth(reading: Reading) -> float:
    return reading.worth or 0.0


def _game(reading: Reading) -> float:
    return game_value(reading) or 0.0
