"""Which of your backs is held as insurance on another of yours.

A handcuff is the running back next on his club's depth chart behind one you
start: worth little while the starter plays, and the starter's work the week
he does not. Dropping him to make room drops the insurance with him, so the
drop pick reaches him only once nobody else will do.

The rule:

- the starter is a running back you roster, and either starts in your lineup
  or the best one, or is his club's first on the depth chart;
- the handcuff is a running back you roster at the same club, at the lowest
  depth below the starter's that the catalog lists anyone at — normally two.

Running backs alone: a backup back inherits the work, where a backup receiver
or tight end splits it with the rest of the room.
"""

from collections.abc import Collection, Mapping

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
    backs = [meta for pid in held if (meta := players.get(pid)) and _charted(meta)]
    starters = [m for m in backs if m.player_id in starting or m.depth_chart_order == 1]
    if not starters:
        return {}
    clubs = {m.team for m in starters}
    depths: dict[str, list[int]] = {club: [] for club in clubs}
    for meta in players.values():
        if meta.team in clubs and _charted(meta):
            depths[meta.team].append(meta.depth_chart_order)
    cuffs: dict[str, PlayerInfo] = {}
    for starter in sorted(starters, key=lambda m: m.depth_chart_order):
        below = [d for d in depths[starter.team] if d > starter.depth_chart_order]
        if not below:
            continue
        nxt = min(below)
        for back in backs:
            if back.team == starter.team and back.depth_chart_order == nxt:
                cuffs.setdefault(back.player_id, starter)
    return cuffs


def _charted(meta: PlayerInfo) -> bool:
    """A running back his club lists somewhere on its depth chart."""
    return meta.position == POSITION and meta.team != FREE_AGENT and meta.depth_chart_order > 0
