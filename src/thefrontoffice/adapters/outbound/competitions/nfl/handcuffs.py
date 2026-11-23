"""Which of your backs is held as insurance: behind another of yours, or behind a club's first back.

A handcuff is the running back next on his club's depth chart behind one you
start: worth little while the starter plays, and the starter's work the week
he does not. Dropping him to make room drops the insurance with him, so the
drop pick reaches him only once nobody else will do.

An understudy is the same back behind his club's first back, whoever rosters
that one — you, another manager, nobody. Whether he is worth keeping depends
on how much of the work the first back has and what it would be worth to you,
which the catalog cannot say; `stashed` decides that.

Both read the chart the same way: the back behind is one you roster at the
same club, at the lowest depth below the back ahead that the catalog lists
anyone at — normally two. For a handcuff the back ahead is yours, and either
starts in your lineup or the best one, or is his club's first on the chart.
For an understudy he is his club's first: the lowest depth it lists.

Running backs alone: a backup back inherits the work, where a backup receiver
or tight end splits it with the rest of the room.
"""

from collections.abc import Collection, Iterable, Mapping

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import MIN_GAMES_FOR_AVERAGE
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import eligible_positions
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo, Projection
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import worth
from thefrontoffice.adapters.outbound.competitions.teammates import surname

POSITION = "RB"
"""The position a handcuff is held at, and his starter plays."""


def handcuffs(
    players: Mapping[str, PlayerInfo], held: Collection[str], starting: Collection[str]
) -> dict[str, PlayerInfo]:
    """Each held back next on the depth chart behind a held back who starts, mapped to that starter.

    `players` is the catalog, read for each club's depth chart; `held` your
    roster; `starting` who your lineups start.
    """
    backs = _held(players, held)
    return _next_behind(players, backs, [m for m in backs if m.player_id in starting or m.depth_chart_order == 1])


def understudies(players: Mapping[str, PlayerInfo], held: Collection[str]) -> dict[str, PlayerInfo]:
    """Each held back next on the depth chart behind his club's first back, mapped to that back, whoever holds him."""
    backs = _held(players, held)
    clubs = {m.team for m in backs}
    first: dict[str, PlayerInfo] = {}
    for meta in players.values():
        if meta.team in clubs and _charted(meta):
            ahead = first.get(meta.team)
            if ahead is None or meta.depth_chart_order < ahead.depth_chart_order:
                first[meta.team] = meta
    return _next_behind(players, backs, first.values())


def _held(players: Mapping[str, PlayerInfo], held: Collection[str]) -> list[PlayerInfo]:
    """Your backs on a depth chart."""
    return [meta for pid in held if (meta := players.get(pid)) and _charted(meta)]


def _next_behind(
    players: Mapping[str, PlayerInfo], backs: Collection[PlayerInfo], ahead: Iterable[PlayerInfo]
) -> dict[str, PlayerInfo]:
    """Each of `backs` at the next depth his club lists below one of `ahead`, gaps skipped, mapped to that one."""
    leaders = sorted(ahead, key=lambda m: m.depth_chart_order)
    clubs = {m.team for m in leaders}
    depths: dict[str, list[int]] = {club: [] for club in clubs}
    if clubs:
        for meta in players.values():
            if meta.team in clubs and _charted(meta):
                depths[meta.team].append(meta.depth_chart_order)
    found: dict[str, PlayerInfo] = {}
    for leader in leaders:
        below = [d for d in depths[leader.team] if d > leader.depth_chart_order]
        if not below:
            continue
        nxt = min(below)
        for back in backs:
            if back.team == leader.team and back.depth_chart_order == nxt:
                found.setdefault(back.player_id, leader)
    return found


def _charted(meta: PlayerInfo) -> bool:
    """A running back his club lists somewhere on its depth chart."""
    return meta.position == POSITION and meta.team != FREE_AGENT and meta.depth_chart_order > 0


# ── which of yours are held as insurance ────────────────────────────


def cuffed(state: Week) -> dict[str, PlayerInfo]:
    """Each of your backs held as a handcuff, mapped to the starter he backs up (see `handcuffs`)."""
    starting = state.starter_ids | {slot.player.player_id for slot in state.best if slot.player}
    return handcuffs(state.players, state.roster.player_ids, starting)


WORKHORSE = 0.6
"""Snap share over a club's first back's last `ROLE_GAMES` games at which the backfield is his.

Most of the snaps, not half: below it the room is a committee, and the back
next on the chart inherits a share of a share when the first one sits.
"""


def stashed(state: Week) -> dict[str, PlayerInfo]:
    """Each of your backs held as a stash, mapped to the workhorse he would replace.

    A stash is an understudy (see `understudies`) whose club's first back is:

    - not ruled out — where he is, the understudy is already the starter, and
      his own figures say so;
    - a workhorse: `WORKHORSE` of the snaps over his last games, at least
      `MIN_GAMES_FOR_AVERAGE` of them;
    - worth starting for you: his points a game over those games beat the
      `worth` of the weakest player your best lineup starts in a slot a back
      can fill.

    Wherever any of that is unknown he is not a stash: protecting every backup
    keeps the dead weight on the bench.
    """
    bar = _weakest_back_slot(state)
    if bar is None:
        return {}
    stashes = {}
    for player_id, ahead in understudies(state.players, state.roster.player_ids).items():
        role = state.evidence.roles.get(ahead.player_id)
        if (
            not ruled_out(ahead.injury_status)
            and role is not None
            and role.games >= MIN_GAMES_FOR_AVERAGE
            and role.snap_share is not None
            and role.snap_share >= WORKHORSE
            and role.points > bar
        ):
            stashes[player_id] = ahead
    return stashes


def _weakest_back_slot(state: Week) -> float | None:
    """The `worth` of the weakest player the best lineup starts in a slot a running back can fill."""
    values = [
        value
        for slot in state.best
        if slot.player is not None
        and "RB" in eligible_positions(slot.slot)
        and (value := worth(state, slot.player)) is not None
    ]
    return min(values, default=None)


def insured(state: Week) -> dict[str, tuple[int, str]]:
    """Each back held as insurance, as his place in the drop order and what the drop says of him.

    A stash goes before a handcuff. A handcuff insures points you already
    score: the week your starter sits, he is the one who scores them. A stash
    is a lineup upgrade only if someone else's back gets hurt; losing him
    costs a chance, losing a handcuff costs points. A back who is both is a
    handcuff.
    """
    held = {pid: (STASH, f"stash behind {surname(ahead.name)}") for pid, ahead in stashed(state).items()}
    held |= {pid: (HANDCUFF, f"handcuff to {surname(starter.name)}") for pid, starter in cuffed(state).items()}
    return held


STASH, HANDCUFF, UNKNOWN = 1, 2, 3
"""Places in the drop order after an ordinary player's nought: a stash, a handcuff, then one with nothing to go on."""


def insurance_note(state: Week, player: Projection) -> str:
    """'handcuff to McCaffrey' or 'stash behind McCaffrey' where he is one; empty where he is neither."""
    return insured(state).get(player.player_id, (0, ""))[1]
