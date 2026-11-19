"""Which of your backs is held as insurance: behind another of yours, or behind a club's first back.

A handcuff is the running back next on his club's depth chart behind one you
start: worth little while the starter plays, and the starter's work the week
he does not. Dropping him to make room drops the insurance with him, so the
drop pick reaches him only once nobody else will do.

An understudy is the same back behind his club's first back, whoever rosters
that one — you, another manager, nobody. Whether he is worth keeping depends
on how much of the work the first back has and what it would be worth to you,
which the catalog cannot say; `actions.stashed` decides that.

Both read the chart the same way: the back behind is one you roster at the
same club, at the lowest depth below the back ahead that the catalog lists
anyone at — normally two. For a handcuff the back ahead is yours, and either
starts in your lineup or the best one, or is his club's first on the chart.
For an understudy he is his club's first: the lowest depth it lists.

Running backs alone: a backup back inherits the work, where a backup receiver
or tight end splits it with the rest of the room.
"""

from collections.abc import Collection, Iterable, Mapping

from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo

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
