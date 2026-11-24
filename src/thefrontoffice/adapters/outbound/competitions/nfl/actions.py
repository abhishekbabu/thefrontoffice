"""What the week asks of the manager, as a list of things to do.

The rest of the provider describes the week; this turns the description into
decisions. Every check here is a fact the league state already settles — a
starter ruled out, a slot left empty, a bye next week with nobody behind it —
so it is computed rather than asked of a model, and complete the moment the
page opens. Whether each move is *wise* is the report's question, not this
module's: it finds the decisions, the report argues about them.

Deadlines are only stated where Sleeper publishes one. It gives a game's day
but not its kickoff, and a waiver run's weekday only as an undocumented
number, so a lineup move says "before kickoff, Sun 25 Oct" and a waiver
move says nothing about when.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.news import dated
from thefrontoffice.adapters.outbound.competitions.nfl import views
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    MIN_GAMES_FOR_AVERAGE,
    REGULAR,
    average,
)
from thefrontoffice.adapters.outbound.competitions.nfl.handcuffs import (
    UNKNOWN,
    insurance_note,
    insured,
)
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    LineupChange,
    best_upgrade,
    eligible_positions,
    fits,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    PlayerInfo,
    Projection,
    active,
    by_club,
    open_spots,
)
from thefrontoffice.adapters.outbound.competitions.nfl.roles import falling, protected
from thefrontoffice.adapters.outbound.competitions.nfl.rules import RULED_OUT, STREAMED, THIS_WEEK, listed, ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.slump import CALL_BY, Slump, called, recent, slumps
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import split as split_on
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week, day
from thefrontoffice.adapters.outbound.competitions.nfl.worth import (
    blend,
    filling_in,
    form,
    projected_ahead,
    rest_of_season,
    value,
    worth,
)
from thefrontoffice.adapters.outbound.competitions.teammates import surname
from thefrontoffice.domain.models import Action, MoveSide, Stat, Urgency, urgency_rank

STACKED = 3
"""Starters riding on one real game at which a bad afternoon there is most of a bad week."""

Move = Literal[
    "ir", "hole", "swap", "upgrade", "slump", "stream", "rise", "stack", "teammate", "bye", "deadline", "short", "stash"
]
"""What an item on the list is about: a player IR no longer takes, a starter who cannot play or an empty slot, a swap the bench
allows, a free agent who outscores a starter, a better form call over a slumping starter, a role that grew, a stacked game, a teammate ahead of
one of yours who may sit, next week's byes, the trade deadline, a week ahead left short, a hurt free agent to hold on IR."""

STARTS_NOW: frozenset[Move] = frozenset({"hole", "upgrade", "slump", "stream"})
"""Pickups that go straight into this week's lineup."""

ADDS: frozenset[Move] = frozenset({"hole", "upgrade", "slump", "stream", "rise"})
"""Pickups that add a player to the roster, and so need room on it."""


@dataclass(frozen=True)
class Item:
    """One thing to do, and what it is about — which the rest of the week reads, rather than its key."""

    move: Move
    action: Action

    @property
    def is_pickup(self) -> bool:
        """Whether it adds a player to the roster."""
        return self.action.kind == "waiver" and self.move in ADDS

    @property
    def starts_now(self) -> bool:
        """Whether the player it adds starts this week."""
        return self.action.kind == "waiver" and self.move in STARTS_NOW


def build(
    state: Week,
    games: Mapping[int, Sequence[Game]],
    started: set[str],
    free_agents: Sequence[Projection],
) -> list[Item]:
    """Every decision the week asks for, most urgent first.

    `started` is every club whose game has kicked off, so whose players are
    locked in or out. `free_agents` is the wire best projection first, already
    cut to players with a game this week; a hole the bench cannot fill is
    pointed at the top of it.
    """
    week_games = games.get(state.week, [])
    kickoff = by_club(week_games)

    items = _ir_locked(state)
    items += _lineup(state, started, kickoff, free_agents)
    items += _upgrades(state, free_agents, started, {i.action.player_id for i in items})
    items += _slumps(state, free_agents, started, kickoff, _moved(items))
    items += _streams(state, free_agents, started, kickoff, _moved(items))
    items += _breakouts(state, free_agents, {i.action.player_id for i in items})
    items += _same_game(state, week_games, started, {(i.action.player_id, i.action.replaces) for i in items})
    items += _teammates(state, kickoff, started)
    items += _next_week_byes(state, games.get(state.week + 1, []), [i for i in items if i.is_pickup], free_agents)
    items += _trade_deadline(state)
    items = _with_players(state, _with_drops(state, items, started))
    return sorted(items, key=lambda i: urgency_rank(i.action.urgency))


def _with_players(state: Week, items: list[Item]) -> list[Item]:
    """Each item that moves more than one player, with them side by side and its evidence cut to their news.

    The figures a row would otherwise state in a sentence — role, projection,
    matchup — are the comparison's rows; only what a figure cannot say, a
    headline, stays as evidence. An item that already names its players, or
    moves one, is left as it is.
    """
    known = {**state.projections, **{p.player_id: p for p in state.projected}}
    out = []
    for item in items:
        action = item.action
        outs = [pid for pid in dict.fromkeys((action.replaces, action.drop)) if pid]
        moved: list[tuple[MoveSide, Projection | None]] = [
            ("in", known.get(action.player_id)),
            *(("out", known.get(pid)) for pid in outs),
        ]
        players: list[tuple[MoveSide, Projection]] = [(side, player) for side, player in moved if player is not None]
        if action.players or not outs or len(players) != len(moved):
            out.append(item)
            continue
        # A growing role is the reason a breakout is on the list, and its reason says so already.
        told = frozenset({action.player_id}) if item.move == "rise" else frozenset()
        compared = views.compared(state, players, told)
        update = {"players": compared, "evidence": headlines(state, [player for _, player in players])}
        out.append(replace(item, action=action.model_copy(update=update)))
    return out


def _ir_locked(state: Week) -> list[Item]:
    """Each player held on IR whose designation the league's IR slot no longer takes.

    Sleeper locks the whole roster while one sits there: no lineup change, no
    pickup, until he is activated or released. Questionable is the usual way
    in — a player returns to practice and his IR designation becomes a game
    one. Activating him needs a roster spot, so the item names who to drop
    when none is open — chosen with every pickup's (`_with_drops`), first, so
    no two items name one drop and none drops a player another moves.
    """
    allows = state.league.ir_allows
    items = []
    for player_id in state.roster.ir_ids:
        meta = state.players.get(player_id)
        if meta is None or meta.injury_status.upper() in allows:
            continue
        status = meta.injury_status.lower() or "cleared to play"
        items.append(
            Item(
                "ir",
                Action(
                    kind="lineup",
                    urgency="now",
                    title=f"Move {meta.name} off IR",
                    reason=f"{meta.name} is {status}. Roster locked until he leaves IR.",
                    when="first",
                    player_id=player_id,
                    key=f"ir:{player_id}:{meta.injury_status.upper()}",
                ),
            )
        )
    return items


def _lineup(
    state: Week,
    started: set[str],
    kickoff: Mapping[str, Game],
    free_agents: Sequence[Projection],
) -> list[Item]:
    """Starters who cannot score, empty slots, and swaps the bench allows."""
    # A player whose game has kicked off is locked in or out, so a move
    # involving him is no longer one anybody can make.
    open_changes = [
        c for c in state.changes if c.start.team not in started and not (c.bench and c.bench.team in started)
    ]
    benching = {c.bench.player_id: c for c in open_changes if c.bench}
    filling = [c for c in open_changes if c.bench is None]
    moved: set[str] = set()
    taken: set[str] = set()
    items: list[Item] = []

    for slot in state.lineup:
        player = slot.player
        if player is not None and player.team in started:
            continue
        if player is None:
            why = f"{slot.slot} empty"
            change = next((c for c in filling if c.start.player_id not in moved), None)
        else:
            why = _cannot_play(player, state.scheduled)
            change = benching.get(player.player_id)
        if not why:
            continue

        # The solve only benches a starter somebody is worth more than, and a
        # bench worth nothing this week leaves him in. Whoever is fit and
        # eligible is the cover then, whatever the numbers say.
        if change is None or change.start.player_id in moved:
            cover = _bench_cover(state, slot.slot, started, moved)
            change = (
                LineupChange(slot=slot.slot, start=cover, bench=player, gain=state.ranked(cover)) if cover else None
            )

        if change is not None:
            moved.update({change.start.player_id, *([player.player_id] if player else [])})
            # A starter going out is compared with his cover, figure by figure; an empty slot has nobody to compare.
            projects = "" if player else f" {change.start.name} projects {change.start.points:.2f}."
            reason = f"{why}.{projects}{_caveat(change.start)}"
            # Only the player coming in: the one going out is not playing, and
            # his matchup is beside the point.
            hole = _hole(slot.slot, player)
            items.append(
                Item("hole", _swap(change, "now", reason, kickoff, _evidence(state, [change.start]), key=hole))
            )
            continue

        # The best by this week's worth, matchup in, as Fits ranks the wire (`views.weekly`).
        pick = max(
            (p for p in free_agents if p.position in eligible_positions(slot.slot) and p.player_id not in taken),
            key=lambda p: views.weekly(state, p),
            default=None,
        )
        if pick is None:
            continue
        taken.add(pick.player_id)
        replaces = f" for {player.name}" if player else ""
        items.append(
            Item(
                "hole",
                Action(
                    kind="waiver",
                    urgency="now",
                    title=f"Pick up {pick.name}{replaces}",
                    reason=f"{why}, no bench cover. Best {pick.position} available"
                    + ("." if player else f", projects {pick.points:.2f}."),
                    player_id=pick.player_id,
                    replaces=player.player_id if player else "",
                    evidence=_evidence(state, [pick]),
                    key=_hole(slot.slot, player),
                ),
            )
        )

    for change in open_changes:
        if change.start.player_id not in moved and not (change.bench and change.bench.player_id in moved):
            reason = f"{_worth_over(state, change)}{_caveat(change.start)}"
            both = [change.start, *([change.bench] if change.bench else [])]
            items.append(
                Item("swap", _swap(change, "soon", reason, kickoff, _evidence(state, both), key=_swap_key(change)))
            )
    return items


def _worth_over(state: Week, change: LineupChange) -> str:
    """'Worth 12.87 vs Tyson's 11.49.' — the figures the best lineup chose between, as a teammate check states them."""
    against = f" vs {surname(change.bench.name)}'s {state.ranked(change.bench):.2f}" if change.bench else ""
    return f"Worth {state.ranked(change.start):.2f}{against}."


def _bench_cover(state: Week, slot: str, started: set[str], moved: set[str]) -> Projection | None:
    """The bench player worth most who can play `slot` this week and is still free to move."""
    return max(
        (
            p
            for p in state.bench
            if p.player_id not in moved
            and p.team not in started
            and p.position in eligible_positions(slot)
            and not _cannot_play(p, state.scheduled)
        ),
        key=state.ranked,
        default=None,
    )


def _cannot_play(player: Projection, scheduled: bool) -> str:
    """Why a starter will score nothing this week, or empty if he can."""
    if ruled_out(player.injury_status):
        return f"{player.name} {RULED_OUT[player.injury_status.upper()]}"
    if scheduled and not player.opponent:
        return f"{player.name} has no game this week"
    return ""


def _caveat(player: Projection) -> str:
    """The doubt hanging over the player a move starts, so it is weighed, not missed."""
    if not listed(player.injury_status):
        return ""
    return f" {player.name} is {player.injury_status.lower()}."


def _evidence(state: Week, players: Sequence[Projection], told: frozenset[str] = frozenset()) -> list[Stat]:
    """Each player's matchup and role, then his latest headline, for whoever has them.

    `told` are the players whose growing role the item's reason already states: their line leaves it out.
    """
    lines = []
    for player in players:
        if stat := state.evidence.stat(player, trend=player.player_id not in told):
            lines.append(stat)
        lines += headlines(state, [player])
    return lines


def _hole(slot: str, player: Projection | None) -> str:
    """The problem a forced move solves — this starter out, or this slot empty.

    Keyed on the problem rather than the answer, so a better cover turning up
    makes the old verdict stale instead of making it vanish.
    """
    return f"hole:{player.player_id}" if player else f"hole:{slot}"


def _swap_key(change: LineupChange) -> str:
    return f"swap:{change.start.player_id}:{change.bench.player_id if change.bench else change.slot}"


def _swap(
    change: LineupChange, urgency: Urgency, reason: str, kickoff: Mapping[str, Game], evidence: list[Stat], key: str
) -> Action:
    """A bench player in, a starter out, by the earlier of their two kickoffs."""
    title = (
        f"Start {change.start.name} over {change.bench.name}"
        if change.bench
        else f"Start {change.start.name} at {change.slot}"
    )
    # Either player locks at his own kickoff, so the swap closes at whichever
    # comes first. ISO dates sort as dates.
    teams = [change.start.team, *([change.bench.team] if change.bench else [])]
    dates = sorted(game.date for t in teams if (game := kickoff.get(t)) and game.date)
    return Action(
        kind="lineup",
        urgency=urgency,
        title=title,
        reason=reason,
        when=f"before kickoff, {day(dates[0])}" if dates else "",
        player_id=change.start.player_id,
        replaces=change.bench.player_id if change.bench else "",
        evidence=evidence,
        key=key,
    )


UPGRADE_BY = 3.0
"""Points a free agent must project over the starter he would replace: less is a coin flip, not a claim."""

UPGRADES = 2
"""Upgrades on the list at once. The free-agent page ranks the rest; the list is for the clear ones."""


def _upgrades(state: Week, free_agents: Sequence[Projection], started: set[str], already: set[str]) -> list[Item]:
    """Free agents who simply outscore one of your starters this week: a defense or a kicker to stream, most often.

    Measured against the best lineup, so the bench has already made its moves
    and nobody is credited with a hole a bench player fills. And against the
    starter's season as well as his week, so a star's one bad matchup is not
    a reason to drop him. At a streamed position the starter he replaces is
    the drop — a lineup starts one defense, and nobody keeps a spare — unless
    he is untouchable, when the bench gives up the spot instead. The season check reads both players by the same
    `views.weekly`: their `worth`, times this week's matchup, as Fits does.
    """
    taken: set[str] = set()
    items = []
    for player in free_agents:
        if len(items) == UPGRADES:
            break
        if player.player_id in already or player.team in started:
            continue
        upgrade = best_upgrade(state.best, player)
        if upgrade is None:
            continue
        gain, slot = upgrade
        starter = slot.player
        if starter is None or starter.team in started or starter.player_id in taken or gain < UPGRADE_BY:
            continue
        if views.weekly(state, player) <= views.weekly(state, starter):
            continue
        taken.add(starter.player_id)
        streamed = (
            player.position in STREAMED
            and starter.position == player.position
            and starter.player_id not in state.untouchable
        )
        items.append(
            Item(
                "upgrade",
                Action(
                    kind="waiver",
                    urgency="soon",
                    title=f"Pick up {player.name}, drop {starter.name}"
                    if streamed
                    else f"Pick up {player.name} to start over {starter.name}",
                    reason=f"+{gain:.2f} proj over {starter.name} at {slot.slot}.{_caveat(player)}",
                    player_id=player.player_id,
                    replaces=starter.player_id,
                    drop=starter.player_id if streamed else "",
                    evidence=_evidence(state, [player, starter]),
                    key=f"upgrade:{player.player_id}",
                ),
            )
        )
    return items


def _moved(items: Iterable[Item]) -> set[str]:
    """Every player an item already moves, either way."""
    return {pid for item in items for pid in (item.action.player_id, item.action.replaces) if pid}


def _slumps(
    state: Week, free_agents: Sequence[Projection], started: set[str], kickoff: Mapping[str, Game], already: set[str]
) -> list[Item]:
    """A better player for each starter in trouble (`slump.slumps`), by form rather than projection.

    His projection is the reading his games disagree with, so the slot is
    weighed by `slump.called` instead — form first, the projection a quarter,
    then usage and the matchup; his form since his quarterback changed, where
    it did — over the bench players who can fill it and the wire at his
    position. A player coming in must beat him by `CALL_BY`. A bench player is
    a start; a free agent a pickup that starts, the starter benched rather than
    dropped: a month is not a season.

    Where several starters are in trouble, each candidate goes to one of them:
    the pairs are taken best gain first (`_matched`), so two slumping tight ends
    are not both handed the same streamer.
    """
    found = slumps(state)
    calls = []
    for place in state.lineup:
        starter = place.player
        sunk = found.get(starter.player_id) if starter else None
        theirs = called(state, starter, sunk.since) if starter and sunk else None
        if starter is None or sunk is None or theirs is None or starter.player_id in already or starter.team in started:
            continue
        bench = [
            p
            for p in state.bench
            if p.position in eligible_positions(place.slot)
            and p.team not in started
            and not _cannot_play(p, state.scheduled)
        ]
        wire = [p for p in free_agents if p.position == starter.position and p.team not in started]
        calls += [
            Call(place.slot, starter, sunk, pick, mine, theirs)
            for pick in (*bench, *wire)
            if pick.player_id not in already and (mine := called(state, pick)) is not None and mine - theirs >= CALL_BY
        ]
    items = []
    for call in _matched(calls):
        already.update({call.pick.player_id, call.starter.player_id})
        reason = _form_call(state, call)
        items.append(_called_item("slump", state, call.slot, call.starter, call.pick, call.gain, reason, kickoff))
    return items


@dataclass(frozen=True)
class Call:
    """One player who could take a troubled starter's slot, and the two form calls between them."""

    slot: str
    starter: Projection
    sunk: Slump
    pick: Projection
    mine: float
    theirs: float

    @property
    def gain(self) -> float:
        return self.mine - self.theirs


def _matched(calls: Sequence[Call]) -> list[Call]:
    """Each starter given at most one player and each player given to at most one starter, the biggest gains first."""
    taken: set[str] = set()
    chosen = []
    for call in sorted(calls, key=lambda call: -call.gain):
        if call.starter.player_id in taken or call.pick.player_id in taken:
            continue
        taken.update({call.starter.player_id, call.pick.player_id})
        chosen.append(call)
    return chosen


def _called_item(
    move: Move,
    state: Week,
    slot: str,
    starter: Projection,
    pick: Projection,
    gain: float,
    reason: str,
    kickoff: Mapping[str, Game],
    drop: bool = False,
) -> Item:
    """A form call as a to-do: a start where he is on the bench, a pickup that starts where he is not."""
    evidence = _evidence(state, [pick, starter])
    key = f"{move}:{starter.player_id}"
    if pick.player_id in state.roster.player_ids:
        change = LineupChange(slot=slot, start=pick, bench=starter, gain=round(gain, 2))
        return Item(move, _swap(change, "soon", reason, kickoff, evidence, key=key))
    return Item(
        move,
        Action(
            kind="waiver",
            urgency="soon",
            title=f"Pick up {pick.name}, {'drop' if drop else 'bench'} {starter.name}",
            reason=reason,
            player_id=pick.player_id,
            replaces=starter.player_id,
            drop=starter.player_id if drop else "",
            evidence=evidence,
            key=key,
        ),
    )


def _streams(
    state: Week, free_agents: Sequence[Projection], started: set[str], kickoff: Mapping[str, Game], already: set[str]
) -> list[Item]:
    """A kicker or a defense on the wire better than yours this week by form and matchup (`slump.called`).

    A streamed position has no slump to read — its week is the matchup — so
    each starting kicker and defense is weighed against the wire at his
    position on half form, half a projection that already reads the matchup,
    nudged by the matchup again. The best must beat him by `CALL_BY`; the one
    he replaces is the drop, since nobody keeps a spare.
    """
    items = []
    for place in state.lineup:
        starter = place.player
        if starter is None or starter.position not in STREAMED or starter.player_id in already:
            continue
        theirs = called(state, starter)
        if theirs is None or starter.team in started:
            continue
        scored = [
            (mine, p)
            for p in free_agents
            if p.position == starter.position
            and p.player_id not in already
            and p.team not in started
            and (mine := called(state, p)) is not None
        ]
        if not scored:
            continue
        mine, pick = max(scored, key=lambda pair: pair[0])
        if mine - theirs < CALL_BY:
            continue
        already.update({pick.player_id, starter.player_id})
        reason = (
            f"Form call: {_streamed(state, starter)} vs {_streamed(state, pick)}; {mine:.2f} vs {theirs:.2f} on form."
        )
        items.append(
            _called_item("stream", state, place.slot, starter, pick, mine - theirs, reason, kickoff, drop=True)
        )
    return items


def _streamed(state: Week, player: Projection) -> str:
    """'Lions 6.60/g, vs GB 3rd-toughest': a streamer's form and this week's matchup."""
    pace = recent(state, player.player_id)
    matchup = state.evidence.matchup(player)
    return (
        surname(player.name)
        + (f" {pace:.2f}/g" if pace is not None else "")
        + (f", {views.facing(player, state.scheduled, '')} {views.ease(matchup)}" if matchup else "")
    )


def _form_call(state: Week, call: Call) -> str:
    """'Form call: Warren 4.95/g L4 vs 11.90 proj those weeks · 3.4 yds/tgt (8.1 before). Barner 9.10/g; 9.80 vs
    6.94 on form.'"""
    pace = recent(state, call.pick.player_id)
    paced = f" {pace:.2f}/g" if pace is not None else ""
    return (
        f"Form call: {surname(call.starter.name)} {call.sunk.short()}. {surname(call.pick.name)}{paced}; "
        f"{call.mine:.2f} vs {call.theirs:.2f} on form.{_caveat(call.pick)}"
    )


BREAKOUTS = 2
"""Pickups suggested for a growing role: the strongest few, not every backup who had a big week."""

BREAKOUT_FROM = 5.0
"""Projected points a breakout needs this week: one whose projection has fallen back to
nothing has usually lost the role again — the starter is back."""


def _breakouts(state: Week, free_agents: Sequence[Projection], already: set[str]) -> list[Item]:
    """Free agents whose role jumped last week, while the projections and the league catch up.

    A stash rather than a start: whether he beats a starter this week is the
    free-agent page's question, so the row names the role and leaves the
    lineup alone. But he must be worth more, by `worth`, than the weakest
    starter he could replace: a role that grew into less than you start
    already is not a pickup.
    """
    rising = sorted(
        (
            p
            for p in free_agents
            if p.player_id in state.evidence.trends
            and p.player_id not in already
            and p.points >= BREAKOUT_FROM
            and _beats_a_starter(state, p)
        ),
        key=lambda p: -state.evidence.trends[p.player_id].rise,
    )
    items = []
    for player in rising[:BREAKOUTS]:
        trend = state.evidence.trends[player.player_id]
        items.append(
            Item(
                "rise",
                Action(
                    kind="waiver",
                    urgency="soon",
                    title=f"Pick up {player.name}",
                    reason=f"Role growing: {trend.describe()}.",
                    player_id=player.player_id,
                    evidence=_evidence(state, [player], told=frozenset({player.player_id})),
                    key=f"rise:{player.player_id}",
                ),
            )
        )
    return items


def _beats_a_starter(state: Week, player: Projection) -> bool:
    """Whether he is worth more this week (`views.weekly`, matchup in) than the weakest starter he could replace, or
    there is an empty slot he fits."""
    upgrade = best_upgrade(state.lineup, player)
    if upgrade is None:
        return False
    starter = upgrade[1].player
    return starter is None or views.weekly(state, player) > views.weekly(state, starter)


def _with_drops(state: Week, items: list[Item], started: set[str]) -> list[Item]:
    """Every pickup with who to drop for it, or the open spot it can go into.

    The drop is the bench player worth least over the rest of the season
    (`drop_candidate`). An IR activation is given its drop first, since nothing
    else can be added until he leaves IR. Never someone another item moves or
    another item already drops, nobody
    whose game has kicked off (the platform will not release him), nobody the
    best lineup starts, and nobody whose role is growing: that is the player
    this list would tell you to pick up.

    A pickup that fills a hole needs a body whoever it costs, so it names the
    cheapest drop regardless. A breakout is optional, and is dropped from the
    list unless the bench holds someone it already beats by `worth` — trading
    a fourteen-point tight end on a one-week injury for a seven-point flier is
    not a to-do item. Where his projection does not yet beat the drop's, the
    reason says the projection lags; where it already does, that would be false.
    """
    room = open_spots(state.league, state.roster)
    named = {pid for item in items for pid in (item.action.player_id, item.action.replaces) if pid}
    chosen: set[str] = set()
    bench = [p for p in state.bench if p.team not in started]

    # A player coming off IR takes a spot first: until he does, nothing else can be added.
    activated: dict[int, Item] = {}
    for index, item in enumerate(items):
        if item.move != "ir":
            continue
        if room > 0:
            # The open spot is drawn on the bench; the reason does not say it again.
            room -= 1
            continue
        drop = drop_candidate(state, bench, named | chosen)
        if drop is None:
            activated[index] = _reworded(item, reason=f"{item.action.reason} No bench player can be dropped yet.")
            continue
        chosen.add(drop.player_id)
        activated[index] = _reworded(
            item,
            drop=drop.player_id,
            title=f"{item.action.title}, drop {drop.name}",
            reason=f"{item.action.reason} {drop_reason(state, drop)}",
        )

    out = []
    for index, item in enumerate(items):
        action = item.action
        if index in activated or not item.is_pickup:
            out.append(activated.get(index, item))
            continue
        if action.drop:
            # The pickup names its own: the starter it replaces, at a position nobody holds two of.
            chosen.add(action.drop)
            out.append(item)
            continue
        if room > 0:
            # It goes into the open spot, which the bench draws: no drop to name, nothing to add.
            room -= 1
            out.append(item)
            continue
        drop = drop_candidate(state, bench, named | chosen)
        if item.move == "rise" and not _worth_a_spot(state, action.player_id, drop):
            continue
        if drop is None:
            out.append(_reworded(item, reason=f"{action.reason} Roster full; no bench player can be dropped yet."))
            continue
        chosen.add(drop.player_id)
        pickup = state.projections.get(action.player_id)
        lag = item.move == "rise" and pickup is not None and pickup.points <= drop.points
        reason = f"{action.reason} Projections lag a role change." if lag else action.reason
        out.append(
            _reworded(
                item,
                drop=drop.player_id,
                title=f"{action.title}, drop {drop.name}",
                reason=f"{reason} {drop_note(state, drop)}",
            )
        )
    return out


def _reworded(item: Item, **update: str) -> Item:
    return replace(item, action=item.action.model_copy(update=update))


def _worth_a_spot(state: Week, player_id: str, drop: Projection | None) -> bool:
    """Whether an optional pickup is worth more than the player it would cost, both read by the same `value`."""
    pickup = state.projections.get(player_id)
    if drop is None or pickup is None:
        return False
    return value(state, pickup) > value(state, drop)


STARTER_DROP_BY = 3.0
"""Points a game of rest-of-season worth by which a starter in your lineup as set must trail the bench player who
would otherwise go — his role no better — before he is the drop instead: under it, the lineup you set wins."""


def drop_candidate(state: Week, among: Iterable[Projection], keep: set[str]) -> Projection | None:
    """The player it costs least to lose: never one kept or marked untouchable, one the best lineup starts, nor
    one whose role grew last week.

    Ranked first by where his role is heading (`roles`), then by what he is
    worth for the rest of the season (`worth.rest_of_season`). A player whose
    role is falling goes before everyone else, and one whose role is rising or
    who leads his club's work after everyone else: a season average and a
    projection both lag a role, and the drop is the least reversible move.
    A stash, then a handcuff, comes after every ordinary player of his rank
    (see `insured`): his worth is the week the back ahead of him misses, which
    no figure here shows. A player with nothing to go on — no games played,
    and no projection ahead or this week — is the last resort: an unknown is
    not a weak player.

    A starter in your lineup as set goes before the bench's choice only where
    his role ranks no better and he trails it by `STARTER_DROP_BY`; and where
    nobody else is left.
    """
    keep = keep | state.untouchable  # The manager's own call, which no figure overrules.
    starting = {slot.player.player_id for slot in state.best if slot.player}
    candidates = [
        p
        for p in among
        if p.player_id not in keep and p.player_id not in state.evidence.trends and p.player_id not in starting
    ]
    held = insured(state) if candidates else {}

    def weakest(player: Projection) -> tuple[int, int, float, float]:
        value = _keep_value(state, player)
        rank = UNKNOWN if value is None else held.get(player.player_id, (0, ""))[0]
        return _role_rank(state, player), rank, value or 0.0, player.points

    bench = min((p for p in candidates if p.player_id not in state.starter_ids), key=weakest, default=None)
    starters = sorted((p for p in candidates if p.player_id in state.starter_ids), key=weakest)
    if bench is None:
        return starters[0] if starters else None
    benched = weakest(bench)
    clearly = [
        p
        for p in starters
        if (mine := weakest(p))[0] <= benched[0] and mine[1] == 0 and mine[2] <= benched[2] - STARTER_DROP_BY
    ]
    return clearly[0] if clearly else bench


def _keep_value(state: Week, player: Projection) -> float | None:
    found = rest_of_season(state, player)
    return worth(state, player) if found is None else found


def _role_rank(state: Week, player: Projection) -> int:
    """0 for a falling role, 2 for one protected (`roles.protected`), 1 otherwise."""
    return 0 if falling(state, player.player_id) else 2 if protected(state, player) else 1


def _kept_for(state: Week, player: Projection) -> str:
    """'8.67/g season, 12.10/g ahead': the figures `worth.rest_of_season` read him by, those he has."""
    figures = []
    if (played := average(state.evidence, player.player_id)) is not None:
        figures.append(f"{played:.2f}/g season")
    if (ahead := projected_ahead(state, player)) is not None:
        figures.append(f"{ahead:.2f}/g ahead")
    return ", ".join(figures)


def _why_drop(state: Week, player: Projection) -> str:
    """Why he is the one: whose handcuff or stash he is, that his role is falling and how, or that he is the weakest."""
    if note := insurance_note(state, player):
        return note
    found = falling(state, player.player_id)
    return f"role falling: {found.describe()}" if found else "weakest on bench"


def drop_note(state: Week, player: Projection) -> str:
    """'Flournoy: role falling: target share 9%, was 15%, falling; Pickens back since week 10 (9.55/g season,
    8.91/g ahead).' — why he is the drop, beside a comparison of his week: his role and his rest of season, which
    no row there says, and whose handcuff or stash he is, or that his recent points were fill-in work, with what
    he scores beside the teammate back.
    """
    why = _why_drop(state, player)
    split = filling_in(state, player)
    if split is not None and (beside := form(state, player)) is not None:
        why += f", {beside:.2f}/game with {surname(split.teammate.name)}"
    kept = _kept_for(state, player)
    return f"{player.name}: {why}" + (f" ({kept})." if kept else ".")


def drop_reason(state: Week, player: Projection) -> str:
    """'Drop X (10.10/g season, 7.00/g ahead), weakest on bench': the figures his rest of season was read from.

    A handcuff or a stash says so instead, since he is only the pick once nobody else is left; a falling role says how.
    """
    kept = _kept_for(state, player)
    shown = f" ({kept})" if kept else ""
    return f"Drop {player.name}{shown}, {_why_drop(state, player)}."


def _same_game(
    state: Week, week_games: Sequence[Game], started: set[str], listed_moves: set[tuple[str, str]]
) -> list[Item]:
    """Games carrying three or more of your starters, with the bench start that spreads them.

    Players in one game rise and fall together — the same pace, the same
    weather, a blowout that sits the starters — so three of them is one bet
    placed three times. That is a wider week, not a worse one: when you are
    behind it is the chance you need, and the forecast prices the swap, so the
    row says which way it cuts rather than telling anyone to break it up.
    """
    game_of = by_club(week_games)
    starters = [slot.player for slot in state.lineup if slot.player]
    stacks: dict[tuple[str, str], list[Projection]] = defaultdict(list)
    for player in starters:
        game = game_of.get(player.team)
        if game is not None and player.team not in started:
            stacks[(game.away, game.home)].append(player)

    items = []
    for (away, home), stacked in stacks.items():
        if len(stacked) < STACKED:
            continue
        out = min(stacked, key=lambda p: p.points)
        apart = [
            p
            for p in state.bench
            if p.opponent
            and p.team not in started
            and p.team not in (away, home)
            and not ruled_out(p.injury_status)
            and fits(state.league.starting_slots, [s for s in starters if s.player_id != out.player_id] + [p])
        ]
        swap = max(apart, key=lambda p: p.points, default=None)
        if swap is None or (swap.player_id, out.player_id) in listed_moves:
            continue
        items.append(
            Item(
                "stack",
                Action(
                    kind="lineup",
                    urgency="later",
                    title=f"{len(stacked)} starters in {away} @ {home}",
                    reason=(
                        f"{join([p.name for p in stacked])}. Start {swap.name} over {out.name} to cut the risk "
                        "if you're favored; keep the stack if not."
                    ),
                    player_id=swap.player_id,
                    replaces=out.player_id,
                    key=f"stack:{away}:{home}",
                ),
            )
        )
    return items


WORK_POSITIONS = frozenset({"RB", "WR", "TE"})
"""Where a teammate's absence hands his snaps and touches to the next man: a quarterback's backup is
nobody's fantasy starter, and a kicker or a defense has no understudy on a roster."""


def _teammates(state: Week, kickoff: Mapping[str, Game], started: set[str]) -> list[Item]:
    """Your players whose teammate at their position, a regular, is on this week's injury report.

    Projections leave a questionable player in and everyone around him where
    they were, so whose work grows if he sits is something to check, not a
    number to trust: the club names its inactives about ninety minutes before
    kickoff. Only a regular counts, since a depth player sitting moves nothing
    — but not only one who out-snaps yours: a starter the injury has already
    held to fewer snaps still takes his targets with him when he sits. It
    names no move, so nothing on the list is dropped for it, and the player it
    is about is kept off the drop list while it stands.

    Only a check worth making is listed: his worth with the teammate sitting
    (`worth_without`) must beat the starter a bench player would replace, or,
    for a starter, at least match the best bench player who could take his
    slot — both by `value`. One that would not is no decision, and a watch
    note would only be noise beside the ones that are.
    """
    roles = state.evidence.roles
    items = []
    for player_id in active(state.roster):
        mine = state.projections.get(player_id)
        if (
            mine is None
            or mine.position not in WORK_POSITIONS
            or not mine.opponent
            or mine.team in started
            or ruled_out(mine.injury_status)
        ):
            continue
        regulars = sorted(
            (
                (other, share)
                for other in state.players.values()
                if other.player_id != player_id
                and other.team == mine.team
                and other.position == mine.position
                and other.injury_status.upper() in THIS_WEEK
                and (role := roles.get(other.player_id)) is not None
                and (share := role.snap_share) is not None
                and share >= REGULAR
            ),
            key=lambda pair: -pair[1],
        )
        if not regulars:
            continue
        doubt = [other for other, _ in regulars if not ruled_out(other.injury_status)]
        out = [other for other, _ in regulars if ruled_out(other.injury_status)]
        mine_starts = mine.player_id in state.starter_ids
        rival = _challenger(state, mine, started) if mine_starts else _would_bench(state, mine, started)
        if rival is None and not mine_starts:
            continue
        estimate, found = worth_without(state, mine, [other for other, _ in regulars])
        theirs = None if rival is None else value(state, rival)
        # He must beat a starter to take his place, and only lose to a bench player to give his up.
        if theirs is not None and (estimate < theirs if mine_starts else estimate <= theirs):
            continue
        starter = None if mine_starts else rival
        # Said as his teammate, so neither the page nor a model reads him as one of yours.
        described = ("Teammate " if len(regulars) == 1 else "Teammates ") + join(
            [f"{other.name} ({other.injury_status.lower()}, {share:.0%} of snaps)" for other, share in regulars]
        )
        title, outcome = _teammate_wording(mine, starter, doubt, out)
        weighed = _weighed(estimate, found, rival, theirs)
        evidence = _evidence(state, [mine])
        players = []
        if starter is not None:
            players = views.compared(state, [("in", mine), ("out", starter)], frozenset())
            evidence = headlines(state, [mine, starter])
        game = kickoff.get(mine.team)
        items.append(
            Item(
                "teammate",
                Action(
                    kind="lineup",
                    urgency="soon",
                    title=title,
                    reason=f"{described}. {weighed} {outcome}",
                    when=f"before kickoff, {day(game.date)}" if game and game.date else "",
                    player_id=mine.player_id,
                    evidence=evidence + headlines(state, [other for other, _ in regulars]),
                    players=players,
                    key=f"teammate:{mine.player_id}:" + ",".join(sorted(other.player_id for other, _ in regulars)),
                ),
            )
        )
    return items


TEAMMATE_BUMP = 0.2
"""How much more a player is worth with a regular teammate at his position sitting, where his own games without
that teammate are too few to say (under `MIN_GAMES_FOR_AVERAGE`): a fifth.

A regular's snaps and targets do not all go to the next man — the club spreads them, and some go to
a tight end or a back — so the bump is the share a single beneficiary plausibly picks up, not the
whole of the absent player's line. Generous on purpose: an estimate that still loses to the starter
he would replace leaves no start to make, and that is the item's whole question.
"""


def worth_without(state: Week, player: Projection, teammates: Sequence[PlayerInfo]) -> tuple[float, Split | None]:
    """What he is worth with these teammates sitting, and the split it was read from, if any.

    His `worth` with his points a game in games without a teammate as his form,
    where he has played at least `MIN_GAMES_FOR_AVERAGE` of them (the one with
    most, where several qualify); otherwise his `value` up `TEAMMATE_BUMP`.
    """
    meta = state.players.get(player.player_id)
    splits = [
        found
        for mate in teammates
        if meta is not None
        and (found := split_on(state.evidence, meta, mate)) is not None
        and found.games >= MIN_GAMES_FOR_AVERAGE
    ]
    if splits:
        most = max(splits, key=lambda found: found.games)
        blended = blend(state, player, most.without)
        if blended is not None:
            return blended, most
    return value(state, player) * (1 + TEAMMATE_BUMP), None


def _would_bench(state: Week, mine: Projection, started: set[str]) -> Projection | None:
    """The starter a bench player would replace: the weakest by `value` in a slot he can play.

    None where any such slot is empty (the lineup's own item fills it) or its
    starter's game has kicked off, so there is no start to make.
    """
    eligible = [slot.player for slot in state.lineup if mine.position in eligible_positions(slot.slot)]
    movable = [p for p in eligible if p is not None and p.team not in started]
    if not movable or len(movable) < len(eligible):
        return None
    return min(movable, key=lambda p: value(state, p))


def _challenger(state: Week, mine: Projection, started: set[str]) -> Projection | None:
    """The best bench player by `value` who could take a starter's slot this week; None where nobody could."""
    slot = next(slot.slot for slot in state.lineup if slot.player and slot.player.player_id == mine.player_id)
    return max(
        (
            p
            for p in state.bench
            if p.team not in started and p.position in eligible_positions(slot) and not _cannot_play(p, state.scheduled)
        ),
        key=lambda p: value(state, p),
        default=None,
    )


def _weighed(estimate: float, found: Split | None, rival: Projection | None, theirs: float | None) -> str:
    """'7.00/game in 3 games without Tate: worth 9.80 vs Tyson's 9.40.' — the figures the check was decided on."""
    basis = (
        f"{found.without:.2f}/game in {found.games} games without {surname(found.teammate.name)}: worth"
        if found
        else f"Worth up {TEAMMATE_BUMP:.0%}:"
    )
    against = f" vs {surname(rival.name)}'s {theirs:.2f}" if rival is not None and theirs is not None else ""
    return f"{basis} {estimate:.2f}{against}."


def _teammate_wording(
    mine: Projection, starter: Projection | None, doubt: list[PlayerInfo], out: list[PlayerInfo]
) -> tuple[str, str]:
    """The title and the last of the reason for a teammate check: the decision it leaves you.

    A bench player is a start to make if the teammate sits, over the starter
    he would replace; a starter is one to leave in. Either way the teammate
    is named as the condition, never as a player of yours.
    """
    if doubt:
        names = join([o.name for o in doubt])
        sits = "sits" if len(doubt) == 1 else "sit"
        title = (
            f"Start {mine.name} over {starter.name} if {names} {sits}"
            if starter
            else f"Keep {mine.name} in: more work if {names} {sits}"
        )
        return title, "Inactives are out ~90 min before kickoff."
    names = join([o.name for o in out])
    if starter:
        return f"Start {mine.name} over {starter.name}: {names} out", "His projection may not count the extra work."
    return f"More work for {mine.name} with {names} out", "His projection may not count the extra work."


def headlines(state: Week, players: Sequence[Projection | PlayerInfo]) -> list[Stat]:
    """Each player's latest headline, and his club's latest story: once, where two of them share a club."""
    stats: list[Stat] = []
    told: set[str] = set()
    for player in players:
        stats += [
            Stat(label=player.name, value=f"News, {dated(a)}: {a.headline}", url=a.url)
            for a in state.news.latest(player.player_id)
        ]
        for story in state.news.team(player.player_id, limit=1):
            if story.article.article_id not in told:
                told.add(story.article.article_id)
                said = f"{story.kind}, {dated(story.article)}: {story.article.headline}"
                stats.append(Stat(label=player.name, value=said, url=story.article.url))
    return stats


def _next_week_byes(
    state: Week, next_games: Sequence[Game], pickups: Sequence[Item], free_agents: Sequence[Projection]
) -> list[Item]:
    """Positions next week's byes would leave short, while there is time to fix it.

    Asked of the starters only: a bench player on bye costs nothing. A
    position is short when fewer bench players can cover it than starters
    are missing from it — and a player in injured reserve or taxi covers
    nothing, since he cannot be started. A player the list already picks up
    (`pickups`) covers it as a bench player would.
    """
    if not next_games:
        return []
    playing = by_club(next_games)
    wire = {p.player_id: p for p in free_agents}
    added = [wire[item.action.player_id] for item in pickups if item.action.player_id in wire]
    week = state.week + 1

    missing: dict[str, list[Projection]] = defaultdict(list)
    for slot in state.lineup:
        if slot.player and slot.player.team not in playing:
            missing[slot.player.position].append(slot.player)

    items = []
    for position, out in missing.items():
        cover = [
            p
            for p in (*state.bench, *added)
            if p.position == position and p.team in playing and not ruled_out(p.injury_status)
        ]
        if len(cover) >= len(out):
            continue
        names = join([p.name for p in out])
        behind = f"only {join([p.name for p in cover])} behind" if cover else f"no bench {position}"
        best = _best_streamer(state, position, playing) if position in STREAMED else None
        named = f": {best.name}" if best else ""
        items.append(
            Item(
                "bye",
                Action(
                    kind="waiver",
                    urgency="later",
                    title=f"Find a {position} for week {week}{named}",
                    reason=f"{names} on bye; {behind}."
                    + (f" Best available: {_upcoming(state, best)}." if best else ""),
                    when=f"week {week}",
                    player_id=out[0].player_id,
                    key=f"bye:{week}:{position}",
                ),
            )
        )
    return items


def _best_streamer(state: Week, position: str, playing: Mapping[str, Game]) -> Projection | None:
    """The free agent projected most next week at a streamed position, with a game and no ruling against him;
    None where next week's projections did not load. A kicker's or a defense's week is its matchup, which his
    projection prices, so it alone names him."""
    return max(
        (
            p
            for pid, p in state.upcoming.items()
            if pid not in state.owned
            and p.position == position
            and p.team in playing
            and p.opponent
            and not ruled_out(p.injury_status)
            and p.points > 0
        ),
        key=lambda p: p.points,
        default=None,
    )


def _upcoming(state: Week, player: Projection) -> str:
    """'Kai Free (K, NYJ), 9.10 proj vs NE, 3rd-easiest': who, his projection, and the matchup it rests on."""
    matchup = state.evidence.matchup(player)
    ease = f", {views.ease(matchup)}" if matchup else ""
    return f"{player.name} ({player.position}, {player.team}), {player.points:.2f} proj vs {player.opponent}{ease}"


def _trade_deadline(state: Week) -> list[Item]:
    """The deadline, once it is close enough that waiting means missing it."""
    deadline = state.league.trade_deadline
    if not deadline or not state.week <= deadline <= state.week + 1:
        return []
    final = deadline == state.week
    return [
        Item(
            "deadline",
            Action(
                kind="trade",
                urgency="soon" if final else "later",
                title="Make any trades this week" if final else "Line up any trades now",
                # The week is said once, as the deadline: the title already says how close it is.
                reason="Trade deadline.",
                when=f"week {deadline}",
                key=f"deadline:{deadline}",
            ),
        )
    ]


def wire(state: Week, signable: Callable[[str], bool]) -> Sequence[Projection]:
    """Who could be picked up and play this week, best projection first.

    Cut to players with a game and no ruling against them: the wire is asked
    to fill a hole, and a player on bye fills nothing.
    """
    return sorted(
        (
            p
            for pid, p in state.projections.items()
            if pid not in state.owned and p.opponent and not ruled_out(p.injury_status) and signable(pid)
        ),
        key=lambda p: -p.points,
    )


def join(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
