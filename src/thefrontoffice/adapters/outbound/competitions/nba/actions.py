"""What a basketball week asks of the manager, as a list of things to do.

Three kinds besides the IL move (`week.off_il`): a bench player to start over
a starter today, a free agent to stream in for the weakest player you could
drop, and that drop.

Yahoo sets a basketball lineup day by day, so a start is today's: a bench
player whose game today is still to come, in for a starter who has no game
today or is ruled out of it, or for one clearly weaker a game. Nobody with no
game today is ever started, however much his week is worth. A stream is
weighed on worth this week (`worth.Reading.worth`: a game's value × minutes
nudge × games left), but never at the cost of a better player a game: the
games are this week's, the player let go is gone for good.
"""

from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.nba import views
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, fits, ruled_out
from thefrontoffice.adapters.outbound.competitions.nba.week import BENCH, Today, off_il
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import Action, Held

MARGIN = 0.2
"""How much more a player must be worth than the one he would replace — a game, or this week: a fifth.

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
    today: Today | None = None,
) -> list[Action]:
    """Every decision the week asks for: IL moves first, then today's starts, then pickups each with its drop.

    `today` is the day's games while it falls inside the week; None leaves out starts, which turn on it.
    """
    items = off_il(list(roster))
    items += starts(roster, readings, by_points, today)
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


def starts(
    roster: Sequence[YahooPlayer], readings: Mapping[str, Reading], by_points: bool, today: Today | None
) -> list[Action]:
    """Bench players to start today over a starter whose slot they can fill, the biggest gain a game first.

    Only a bench player whose game today has not tipped off, and who is not
    ruled out of it, goes in. He goes in for a starter who will score nothing
    today — no game, or ruled out — or for one whose game is also still to
    come and whom he beats by `MARGIN` a game. A starter whose game is under
    way is locked. Each starter is named once, against the weakest he could
    replace, and only a bench player Yahoo lets into that slot (`rules.fits`).
    None without `today`: a start set on the week rather than the day can put
    in a player with no game tonight.
    """
    if today is None:
        return []
    lineup = [
        r for p in roster if held(p) == "starter" and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    bench = [
        r
        for p in roster
        if held(p) == "bench"
        and not ruled_out(p.status)
        and _to_come(today, p)
        and (r := readings.get(p.player_key))
        and r.per_game is not None
    ]
    pairs = []
    for candidate in bench:
        for starter in lineup:
            game = today.game(starter.player.team)
            if not fits(starter.player.slot, candidate.player.position) or (game and game.status in STARTED):
                continue
            idle = game is None or ruled_out(starter.player.status)
            if idle or beats(_game(candidate), _game(starter)):
                gain = _game(candidate) - (0.0 if idle else _game(starter))
                pairs.append((idle, gain, candidate, starter))
    pairs.sort(key=lambda pair: (not pair[0], -pair[1]))
    taken: set[str] = set()
    items = []
    for idle, gain, candidate, starter in pairs:
        if len(items) == STARTS:
            break
        if candidate.player.player_key in taken or starter.player.player_key in taken:
            continue
        taken |= {candidate.player.player_key, starter.player.player_key}
        why = (
            f"{starter.player.name} {'is ruled out' if today.game(starter.player.team) else 'has no game'} today"
            if idle
            else f"+{gain:.1f} {_unit(by_points)} a game at {starter.player.slot}"
        )
        items.append(
            Action(
                kind="lineup",
                urgency="now",
                title=f"Start {candidate.player.name} over {starter.player.name} today",
                reason=f"{why}; {candidate.player.name} plays {_matchup(today, candidate.player)}.",
                player_id=candidate.player.player_key,
                replaces=starter.player.player_key,
                players=views.compared(
                    [("in", "bench", candidate), ("out", "starter", starter)],
                    by_points,
                ),
                key=f"start:{today.day.isoformat()}:{candidate.player.player_key}:{starter.player.player_key}",
            )
        )
    return items


def _to_come(today: Today, player: YahooPlayer) -> bool:
    """Whether his club plays today and has yet to tip off: the lineup can still be changed for it."""
    game = today.game(player.team)
    return game is not None and game.status not in STARTED


STARTED = frozenset({"in_game", "complete"})
"""Sleeper's statuses for a game that has tipped off: its players are locked in or out."""


def _matchup(today: Today, player: YahooPlayer) -> str:
    """'vs TOR' or '@ BOS': his game today."""
    game = today.game(player.team)
    found = game.opponent_of(player.team.upper()) if game else None
    if found is None:
        return "today"
    opponent, home = found
    return f"vs {opponent}" if home else f"@ {opponent}"


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
                    f"+{gain:.1f} {_unit(by_points)} this week. {drop.player.name}: weakest you can drop"
                    + _drags(drop)
                    + "."
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
    """Whether `pickup` beats `drop` this week, and is at least as good a game.

    The extra games are this week's and the player let go is gone for good, so
    a stream never trades down a game for them.
    """
    return beats(_worth(pickup), _worth(drop)) and _game(pickup) >= _game(drop)


PROVISIONAL = " Provisional: schedule not final."
"""What an item weighed on games left adds while the NBA has days of the week to schedule."""


def _drags(reading: Reading) -> str:
    """What drags his value, in a category league: ' (FG% .380 · 2.9 TO)'; nothing where nothing does."""
    drags = views.weak(reading)
    return f" ({drags})" if drags else ""


def _pending(reading: Reading) -> str:
    return PROVISIONAL if reading.provisional else ""


def _worth(reading: Reading) -> float:
    return reading.worth or 0.0


def _game(reading: Reading) -> float:
    return game_value(reading) or 0.0
