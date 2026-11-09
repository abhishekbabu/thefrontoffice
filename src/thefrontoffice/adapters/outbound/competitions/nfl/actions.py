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

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import RISES, average, season_average
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    LineupChange,
    best_upgrade,
    eligible_positions,
    fits,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import Game, PlayerInfo, Projection, active, by_club
from thefrontoffice.adapters.outbound.competitions.nfl.news import dated
from thefrontoffice.adapters.outbound.competitions.nfl.rules import RULED_OUT, STREAMED, THIS_WEEK, listed, ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week, day
from thefrontoffice.domain.models import Action, Stat, Urgency, urgency_rank

STACKED = 3
"""Starters riding on one real game at which a bad afternoon there is most of a bad week."""

Move = Literal["ir", "hole", "swap", "upgrade", "rise", "stack", "teammate", "bye", "deadline", "short"]
"""What an item on the list is about: a player IR no longer takes, a starter who cannot play or an empty slot, a swap the bench
allows, a free agent who outscores a starter, a role that grew, a stacked game, a teammate ahead of
one of yours who may sit, next week's byes, the trade deadline, a week ahead left short."""

STARTS_NOW: frozenset[Move] = frozenset({"hole", "upgrade"})
"""Pickups that go straight into this week's lineup."""

ADDS: frozenset[Move] = frozenset({"hole", "upgrade", "rise"})
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

    items = _ir_locked(state, started)
    items += _lineup(state, started, kickoff, free_agents)
    items += _upgrades(state, free_agents, started, {i.action.player_id for i in items})
    items += _breakouts(state, free_agents, {i.action.player_id for i in items})
    items += _same_game(state, week_games, started, {(i.action.player_id, i.action.replaces) for i in items})
    items += _teammates(state, kickoff, started)
    items += _next_week_byes(state, games.get(state.week + 1, []))
    items += _trade_deadline(state)
    return sorted(_with_drops(state, items, started), key=lambda i: urgency_rank(i.action.urgency))


def _ir_locked(state: Week, started: set[str]) -> list[Item]:
    """Each player held on IR whose designation the league's IR slot no longer takes.

    Sleeper locks the whole roster while one sits there: no lineup change, no
    pickup, until he is activated or released. Questionable is the usual way
    in — a player returns to practice and his IR designation becomes a game
    one. Activating him needs a roster spot, so the item names who to drop
    when none is open, chosen as any pickup's drop is.
    """
    allows = state.league.ir_allows
    open_spots = state.league.roster_spots - len(active(state.roster))
    items = []
    for player_id in state.roster.ir_ids:
        meta = state.players.get(player_id)
        if meta is None or meta.injury_status.upper() in allows:
            continue
        status = meta.injury_status.lower() or "cleared to play"
        reason = (
            f"{meta.name} is {status}, and this league's IR slot takes only {join(sorted(allows))}. "
            "Sleeper refuses every lineup change and pickup until he leaves it."
        )
        drop = None
        if open_spots > 0:
            open_spots -= 1
            reason += " You have a roster spot open for him."
        else:
            drop = drop_candidate(state, (p for p in state.bench if p.team not in started), set())
            reason += f" {_drop_reason(state, drop)}" if drop else " Nobody on the bench can be released yet."
        items.append(
            Item(
                "ir",
                Action(
                    kind="lineup",
                    urgency="now",
                    title=f"Move {meta.name} off IR" + (f", drop {drop.name}" if drop else ""),
                    reason=reason,
                    when="before any other move",
                    player_id=player_id,
                    drop=drop.player_id if drop else "",
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
            why = f"Your {slot.slot} slot is empty"
            change = next((c for c in filling if c.start.player_id not in moved), None)
        else:
            why = _cannot_play(player, state.scheduled)
            change = benching.get(player.player_id)
        if not why:
            continue

        # The projection solve only benches a starter somebody outscores, and
        # Sleeper can still project a player it has ruled out. Whoever is
        # fit and eligible is the cover then, whatever the numbers say.
        if change is None or change.start.player_id in moved:
            cover = _bench_cover(state, slot.slot, started, moved)
            change = LineupChange(slot=slot.slot, start=cover, bench=player) if cover else None

        if change is not None:
            moved.update({change.start.player_id, *([player.player_id] if player else [])})
            reason = f"{why}. {change.start.name} projects {change.start.points:.2f}.{_caveat(change.start)}"
            # Only the player coming in: the one going out is not playing, and
            # his matchup is beside the point.
            hole = _hole(slot.slot, player)
            items.append(
                Item("hole", _swap(change, "now", reason, kickoff, _evidence(state, [change.start]), key=hole))
            )
            continue

        pick = next(
            (p for p in free_agents if p.position in eligible_positions(slot.slot) and p.player_id not in taken),
            None,
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
                    reason=(
                        f"{why}, and nobody on your bench can play {slot.slot}. {pick.name} is the best "
                        f"projected {pick.position} available, at {pick.points:.2f}."
                    ),
                    player_id=pick.player_id,
                    replaces=player.player_id if player else "",
                    evidence=_evidence(state, [pick]),
                    key=_hole(slot.slot, player),
                ),
            )
        )

    for change in open_changes:
        if change.start.player_id not in moved and not (change.bench and change.bench.player_id in moved):
            reason = f"+{change.gain:.2f} proj pts.{_caveat(change.start)}"
            both = [change.start, *([change.bench] if change.bench else [])]
            items.append(
                Item("swap", _swap(change, "soon", reason, kickoff, _evidence(state, both), key=_swap_key(change)))
            )
    return items


def _bench_cover(state: Week, slot: str, started: set[str], moved: set[str]) -> Projection | None:
    """The best bench player who can play `slot` this week and is still free to move."""
    return max(
        (
            p
            for p in state.bench
            if p.player_id not in moved
            and p.team not in started
            and p.position in eligible_positions(slot)
            and not _cannot_play(p, state.scheduled)
        ),
        key=lambda p: p.points,
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
    return f" {player.name} is listed {player.injury_status.lower()} — check his status before his game."


def _evidence(state: Week, players: Sequence[Projection]) -> list[Stat]:
    """Each player's matchup and role, then his latest headline, for whoever has them."""
    lines = []
    for player in players:
        if stat := state.evidence.stat(player):
            lines.append(stat)
        lines += _news(state, [player])
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
    the drop — a lineup starts one defense, and nobody keeps a spare.
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
        if player.points <= season_average(state.evidence, starter):
            continue
        taken.add(starter.player_id)
        streamed = player.position in STREAMED and starter.position == player.position
        items.append(
            Item(
                "upgrade",
                Action(
                    kind="waiver",
                    urgency="soon",
                    title=f"Pick up {player.name}, drop {starter.name}"
                    if streamed
                    else f"Pick up {player.name} to start over {starter.name}",
                    reason=(
                        f"{player.name} projects {player.points:.2f}, {gain:.2f} more than {starter.name} "
                        f"at {slot.slot} this week.{_caveat(player)}"
                        + (f" Drop {starter.name}: a lineup starts one {player.position}." if streamed else "")
                    ),
                    player_id=player.player_id,
                    replaces=starter.player_id,
                    drop=starter.player_id if streamed else "",
                    evidence=_evidence(state, [player, starter]),
                    key=f"upgrade:{player.player_id}",
                ),
            )
        )
    return items


BREAKOUTS = 2
"""Pickups suggested for a growing role: the strongest few, not every backup who had a big week."""

BREAKOUT_FROM = 5.0
"""Projected points a breakout needs this week: one whose projection has fallen back to
nothing has usually lost the role again — the starter is back."""


def _breakouts(state: Week, free_agents: Sequence[Projection], already: set[str]) -> list[Item]:
    """Free agents whose role jumped last week, while the projections and the league catch up.

    A stash rather than a start: whether he beats a starter this week is the
    free-agent page's question, so the row names the role and leaves the
    lineup alone.
    """
    rising = sorted(
        (
            p
            for p in free_agents
            if p.player_id in state.evidence.trends
            and p.player_id not in already
            and p.points >= BREAKOUT_FROM
            and best_upgrade(state.lineup, p) is not None
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
                    title=f"Pick up {player.name} while his role grows",
                    reason=(
                        f"{player.name}'s {trend.describe()}. He projects {player.points:.2f} at {player.position}, "
                        "and a projection is slow to read a role that has just changed."
                    ),
                    player_id=player.player_id,
                    evidence=_evidence(state, [player]),
                    key=f"rise:{player.player_id}",
                ),
            )
        )
    return items


def _with_drops(state: Week, items: list[Item], started: set[str]) -> list[Item]:
    """Every pickup with who to drop for it, or the open spot it can go into.

    The drop is the bench player worth least for the rest of the season, by
    his average a game — not this week's projection, which reads a starter on
    bye as nothing. Never someone another item moves, nobody whose game has
    kicked off (the platform will not release him), and nobody whose role is
    growing: that is the player this list would tell you to pick up.

    A pickup that fills a hole needs a body whoever it costs, so it names the
    cheapest drop regardless. A breakout is optional, and is dropped from the
    list unless the bench holds someone it already beats — trading a
    fourteen-point tight end on a one-week injury for a seven-point flier is
    not a to-do item.
    """
    # A player coming off IR takes a spot first: until he does, nothing else can be added.
    open_spots = state.league.roster_spots - len(active(state.roster))
    open_spots -= sum(1 for item in items if item.move == "ir" and not item.action.drop)
    named = {pid for item in items for pid in (item.action.player_id, item.action.replaces) if pid}
    chosen = {item.action.drop for item in items if item.move == "ir" and item.action.drop}
    out = []
    for item in items:
        action = item.action
        if not item.is_pickup:
            out.append(item)
            continue
        if action.drop:
            # The pickup names its own: the starter it replaces, at a position nobody holds two of.
            chosen.add(action.drop)
            out.append(item)
            continue
        if open_spots > 0:
            open_spots -= 1
            out.append(_reworded(item, reason=f"{action.reason} You have a roster spot open for him."))
            continue
        drop = drop_candidate(state, (p for p in state.bench if p.team not in started), named | chosen)
        if item.move == "rise" and not _worth_a_spot(state, action.player_id, drop):
            continue
        if drop is None:
            out.append(
                _reworded(
                    item, reason=f"{action.reason} Your roster is full and nobody on the bench can be released yet."
                )
            )
            continue
        chosen.add(drop.player_id)
        out.append(
            _reworded(
                item,
                drop=drop.player_id,
                title=f"{action.title}, drop {drop.name}",
                reason=f"{action.reason} {_drop_reason(state, drop)}",
            )
        )
    return out


def _reworded(item: Item, **update: str) -> Item:
    return replace(item, action=item.action.model_copy(update=update))


def _worth_a_spot(state: Week, player_id: str, drop: Projection | None) -> bool:
    """Whether an optional pickup is worth more than the player it would cost."""
    pickup = state.projections.get(player_id)
    return drop is not None and pickup is not None and pickup.points > season_average(state.evidence, drop)


def drop_candidate(state: Week, among: Iterable[Projection], keep: set[str]) -> Projection | None:
    """The player it costs least to lose, by his season rather than his week: never one kept, nor one whose role is growing.

    A player whose role is growing is the one a to-do list would tell you to
    pick up, so he is never the one to let go.
    """
    candidates = [p for p in among if p.player_id not in keep and p.player_id not in state.evidence.trends]
    return min(candidates, key=lambda p: (season_average(state.evidence, p), p.points), default=None)


def _drop_reason(state: Week, player: Projection) -> str:
    played = average(state.evidence, player.player_id)
    if played is not None:
        worth = f"{played:.2f} a game this season, {player.points:.2f} projected this week"
    else:
        worth = f"{player.points:.2f} projected this week, with too few games to judge him on more"
    return f"Drop {player.name}, the least on your bench: {worth}."


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
                    title=f"{len(stacked)} starters ride on {away} at {home}",
                    reason=(
                        f"{join([p.name for p in stacked])} all play in it, so one bad game there takes "
                        f"them all down together. Starting {swap.name} ({swap.points:.2f}) for {out.name} "
                        f"({out.points:.2f}) spreads the risk: worth it when you are ahead, and often not when "
                        "you are behind, where you need that game to go well."
                    ),
                    player_id=swap.player_id,
                    replaces=out.player_id,
                    key=f"stack:{away}:{home}",
                ),
            )
        )
    return items


REGULAR = RISES["snaps"][1]
"""Snap share over his last few games at which a player's absence is felt by whoever plays behind him."""

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
        described = join(
            [f"{other.name} ({other.injury_status.lower()}, {share:.0%} of snaps)" for other, share in regulars]
        )
        if doubt:
            title = f"Check whether {join([o.name for o in doubt])} plays before setting {mine.name}"
            outcome = (
                f"If {'he sits' if len(doubt) == 1 else 'they sit'}, more of the work at {mine.position} falls to "
                f"{mine.name}, who projects {mine.points:.2f} as things stand. {mine.team} names its inactives "
                "about 90 minutes before kickoff."
            )
        else:
            title = f"More work for {mine.name} with {join([o.name for o in out])} out"
            outcome = (
                f"Sleeper projects {mine.name} at {mine.points:.2f}; whether that already counts the extra work is "
                "not something the projection says."
            )
        game = kickoff.get(mine.team)
        items.append(
            Item(
                "teammate",
                Action(
                    kind="lineup",
                    urgency="soon",
                    title=title,
                    reason=f"{described} {'is' if len(regulars) == 1 else 'are'} a regular at {mine.position} "
                    f"for {mine.team}. {outcome}",
                    when=f"before kickoff, {day(game.date)}" if game and game.date else "",
                    player_id=mine.player_id,
                    evidence=_evidence(state, [mine]) + _news(state, [other for other, _ in regulars]),
                    key=f"teammate:{mine.player_id}:" + ",".join(sorted(other.player_id for other, _ in regulars)),
                ),
            )
        )
    return items


def _news(state: Week, players: Sequence[Projection | PlayerInfo]) -> list[Stat]:
    """Each player's latest headlines."""
    return [
        Stat(label=player.name, value=f"News, {dated(a)}: {a.headline}")
        for player in players
        for a in state.news.latest(player.player_id)
    ]


def _next_week_byes(state: Week, next_games: Sequence[Game]) -> list[Item]:
    """Positions next week's byes would leave short, while there is time to fix it.

    Asked of the starters only: a bench player on bye costs nothing. A
    position is short when fewer bench players can cover it than starters
    are missing from it — and a player in injured reserve or taxi covers
    nothing, since he cannot be started.
    """
    if not next_games:
        return []
    playing = by_club(next_games)
    week = state.week + 1

    missing: dict[str, list[Projection]] = defaultdict(list)
    for slot in state.lineup:
        if slot.player and slot.player.team not in playing:
            missing[slot.player.position].append(slot.player)

    items = []
    for position, out in missing.items():
        cover = [
            p for p in state.bench if p.position == position and p.team in playing and not ruled_out(p.injury_status)
        ]
        if len(cover) >= len(out):
            continue
        names = join([p.name for p in out])
        verb = "is" if len(out) == 1 else "are"
        behind = (
            f"only {join([p.name for p in cover])} can step in" if cover else f"nobody on your bench plays {position}"
        )
        items.append(
            Item(
                "bye",
                Action(
                    kind="waiver",
                    urgency="later",
                    title=f"Find a {position} for week {week}",
                    reason=f"{names} {verb} on bye, and {behind}.",
                    when=f"week {week}",
                    player_id=out[0].player_id,
                    key=f"bye:{week}:{position}",
                ),
            )
        )
    return items


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
                reason=(
                    f"The league's trade deadline is week {deadline}"
                    + (", so this is the last week to deal." if final else ", next week.")
                ),
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
