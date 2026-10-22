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

from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupChange, eligible_positions
from thefrontoffice.adapters.outbound.competitions.nfl.news import dated
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week, day
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame, WeeklyProjection
from thefrontoffice.domain.models import Action, Stat, Urgency

# Sleeper's statuses for a player who will not play, in the words a person
# would use. Questionable is deliberately absent: most questionable players
# play, and flagging every one buries the starters who will not.
RULED_OUT = {
    "OUT": "is ruled out",
    "IR": "is on injured reserve",
    "PUP": "is on the PUP list",
    "SUS": "is suspended",
    "NA": "is not active",
    "DNR": "is not with a team",
}

URGENCY_ORDER: dict[Urgency, int] = {"now": 0, "soon": 1, "later": 2}


def build(
    state: Week,
    games: dict[int, list[ScheduledGame]],
    free_agents: list[WeeklyProjection],
) -> list[Action]:
    """Every decision the week asks for, most urgent first.

    `free_agents` is the wire best projection first, already cut to players
    with a game this week; a hole the bench cannot fill is pointed at the top
    of it.
    """
    week_games = games.get(state.week, [])
    started = {
        club for game in week_games if game.status and game.status != "pre_game" for club in (game.home, game.away)
    }
    kickoff = {club: game.date for game in week_games for club in (game.home, game.away)}

    actions = _lineup(state, started, kickoff, free_agents)
    actions += _next_week_byes(state, games.get(state.week + 1, []))
    actions += _trade_deadline(state)
    return sorted(actions, key=lambda a: URGENCY_ORDER[a.urgency])


def _lineup(
    state: Week,
    started: set[str],
    kickoff: dict[str, str],
    free_agents: list[WeeklyProjection],
) -> list[Action]:
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
    actions: list[Action] = []

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
            reason = f"{why}. {change.start.name} projects {change.start.points:.1f}.{_caveat(change.start)}"
            # Only the player coming in: the one going out is not playing, and
            # his matchup is beside the point.
            hole = _hole(slot.slot, player)
            actions.append(_swap(change, "now", reason, kickoff, _evidence(state, [change.start]), key=hole))
            continue

        pick = next(
            (p for p in free_agents if p.position in eligible_positions(slot.slot) and p.player_id not in taken),
            None,
        )
        if pick is None:
            continue
        taken.add(pick.player_id)
        replaces = f" for {player.name}" if player else ""
        actions.append(
            Action(
                kind="waiver",
                urgency="now",
                title=f"Pick up {pick.name}{replaces}",
                reason=(
                    f"{why}, and nobody on your bench can play {slot.slot}. {pick.name} is the best "
                    f"projected {pick.position} available, at {pick.points:.1f}."
                ),
                player_id=pick.player_id,
                replaces=player.player_id if player else "",
                evidence=_evidence(state, [pick]),
                key=_hole(slot.slot, player),
            )
        )

    for change in open_changes:
        if change.start.player_id not in moved and not (change.bench and change.bench.player_id in moved):
            reason = f"+{change.gain:.1f} proj pts.{_caveat(change.start)}"
            both = [change.start, *([change.bench] if change.bench else [])]
            actions.append(_swap(change, "soon", reason, kickoff, _evidence(state, both), key=_swap_key(change)))
    return actions


def _bench_cover(state: Week, slot: str, started: set[str], moved: set[str]) -> WeeklyProjection | None:
    """The best bench player who can play `slot` this week and is still free to move."""
    starters = state.starter_ids
    return max(
        (
            p
            for p in state.projected
            if p.player_id not in starters
            and p.player_id not in moved
            and p.team not in started
            and p.position in eligible_positions(slot)
            and not _cannot_play(p, state.scheduled)
        ),
        key=lambda p: p.points,
        default=None,
    )


def _cannot_play(player: WeeklyProjection, scheduled: bool) -> str:
    """Why a starter will score nothing this week, or empty if he can."""
    status = RULED_OUT.get(player.injury_status.upper())
    if status:
        return f"{player.name} {status}"
    if scheduled and not player.opponent:
        return f"{player.name} has no game this week"
    return ""


def _caveat(player: WeeklyProjection) -> str:
    """The doubt hanging over the player a move starts, so it is weighed, not missed."""
    if not player.is_questionable:
        return ""
    return f" {player.name} is listed {player.injury_status.lower()} — check his status before his game."


def _evidence(state: Week, players: list[WeeklyProjection]) -> list[Stat]:
    """Each player's matchup and role, then his latest headline, for whoever has them."""
    lines = []
    for player in players:
        if stat := state.evidence.stat(player):
            lines.append(stat)
        lines += [
            Stat(label=player.name, value=f"News, {dated(a)}: {a.headline}")
            for a in state.news.latest(player.player_id)
        ]
    return lines


def _hole(slot: str, player: WeeklyProjection | None) -> str:
    """The problem a forced move solves — this starter out, or this slot empty.

    Keyed on the problem rather than the answer, so a better cover turning up
    makes the old verdict stale instead of making it vanish.
    """
    return f"hole:{player.player_id}" if player else f"hole:{slot}"


def _swap_key(change: LineupChange) -> str:
    return f"swap:{change.start.player_id}:{change.bench.player_id if change.bench else change.slot}"


def _swap(
    change: LineupChange, urgency: Urgency, reason: str, kickoff: dict[str, str], evidence: list[Stat], key: str
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
    dates = sorted(kickoff[t] for t in teams if kickoff.get(t))
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


def _next_week_byes(state: Week, next_games: list[ScheduledGame]) -> list[Action]:
    """Positions next week's byes would leave short, while there is time to fix it.

    Asked of the starters only: a bench player on bye costs nothing. A
    position is short when fewer bench players can cover it than starters
    are missing from it.
    """
    if not next_games:
        return []
    playing = {club for game in next_games for club in (game.home, game.away)}
    starters = state.starter_ids
    week = state.week + 1

    missing: dict[str, list[WeeklyProjection]] = defaultdict(list)
    for slot in state.lineup:
        if slot.player and slot.player.team not in playing:
            missing[slot.player.position].append(slot.player)

    actions = []
    for position, out in missing.items():
        cover = [
            p
            for p in state.projected
            if p.position == position
            and p.team in playing
            and p.player_id not in starters
            and p.injury_status.upper() not in RULED_OUT
        ]
        if len(cover) >= len(out):
            continue
        names = _join([p.name for p in out])
        verb = "is" if len(out) == 1 else "are"
        behind = (
            f"only {_join([p.name for p in cover])} can step in" if cover else f"nobody on your bench plays {position}"
        )
        actions.append(
            Action(
                kind="waiver",
                urgency="later",
                title=f"Find a {position} for week {week}",
                reason=f"{names} {verb} on bye, and {behind}.",
                when=f"week {week}",
                player_id=out[0].player_id,
                key=f"bye:{week}:{position}",
            )
        )
    return actions


def _trade_deadline(state: Week) -> list[Action]:
    """The deadline, once it is close enough that waiting means missing it."""
    deadline = state.league.trade_deadline
    if not deadline or not state.week <= deadline <= state.week + 1:
        return []
    final = deadline == state.week
    return [
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
        )
    ]


def _join(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
