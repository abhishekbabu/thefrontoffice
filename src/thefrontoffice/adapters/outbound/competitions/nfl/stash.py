"""A free agent to hold in an empty injured-reserve slot until he is back.

An IR slot costs no roster spot, so one left empty is a player for free: a
starter hurt now and back before the playoffs is worth more in December than
the last man on the bench, and nobody can claim him once he is healthy and on
somebody's roster. The slot only takes a player whose designation it allows
(`LeagueRules.ir_allows`), and a claim lands on the roster first — he moves to
IR once it processes — so it needs a spot for that moment: an open one, or the
weakest bench player dropped for it.

Whether he is worth it is read the way a drop is: his recent form beside his
outlook (`worth.FORM_WEIGHT`), where the outlook is his projection over the
weeks after he is back through the fantasy final rather than this week's, which is nought,
times his usage before he was hurt (`worth.usage`).
"""

from collections.abc import Callable, Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.nfl.actions import Item, drop_candidate, drop_reason, headlines
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import MIN_GAMES_FOR_AVERAGE
from thefrontoffice.adapters.outbound.competitions.nfl.injuries import return_week
from thefrontoffice.adapters.outbound.competitions.nfl.model import Game, NFLSource, PlayerInfo, Projection, open_spots
from thefrontoffice.adapters.outbound.competitions.nfl.outlook import weeks_left
from thefrontoffice.adapters.outbound.competitions.nfl.rules import last_regular_week, season_end
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import usage, worth
from thefrontoffice.adapters.outbound.competitions.worth import blend
from thefrontoffice.domain.models import Action, Stat

STASH_FROM = 40.0
"""Projected points from his return through the fantasy final below which he is not worth the claim.

The window runs through the playoffs (`rules.season_end`), so even a player back in the
last regular-season week brings a 6-team bracket's three weeks with him: 40 is those
weeks from a flex-grade starter (about 13 a week). The old 25, set against the regular
season alone, would pass a backup on the bracket weeks by themselves."""

COMPARABLE_BY = 1.0
"""Points a game he may fall short of the weakest bench player and still be worth stashing: about a coin flip."""


def to_do(
    client: NFLSource,
    state: Week,
    schedule: Mapping[int, Sequence[Game]],
    signable: Callable[[str], bool],
    listed: Sequence[Item],
    started: set[str],
) -> list[Item]:
    """The best free agent to stash for each empty IR slot, where one is back before the playoffs and worth it.

    `listed` is the rest of the to-do list: a spot another pickup takes is not
    open for this one, and a player it moves is never the drop.
    """
    empty = state.league.ir_slots - len(state.roster.ir_ids)
    if empty <= 0:
        return []
    last, final = last_regular_week(state.league), season_end(state.league)
    named = {pid for item in listed for pid in (item.action.player_id, item.action.replaces, item.action.drop) if pid}
    back = {
        pid: week
        for pid, meta in state.players.items()
        if pid not in state.owned
        and pid not in named
        and meta.injury_status.upper() in state.league.ir_allows
        and signable(pid)
        and (returns := state.injuries.returns(pid)) is not None
        and (week := return_week(returns, schedule)) is not None
        and week <= last
    }
    if not back:
        return []
    ahead = weeks_left(client, state)
    if not ahead:
        return []

    bench = [p for p in state.bench if p.team not in started]
    weakest = drop_candidate(state, bench, named)
    bar = worth(state, weakest) if weakest else None
    valued = []
    for pid, week in back.items():
        projected = [p.points for w, each in ahead.items() if w >= week and (p := each.get(pid)) and p.points > 0]
        rest = sum(projected)
        if rest < STASH_FROM:
            continue
        recent = _form(state, pid)
        outlook = rest / len(projected)
        value = (blend(recent, outlook) or 0.0) * usage(state, pid)
        if bar is not None and value < bar - COMPARABLE_BY:
            continue
        valued.append((value, pid, week, rest))
    valued.sort(key=lambda row: -row[0])

    room = open_spots(state.league, state.roster) - sum(
        1 for item in listed if (item.is_pickup or item.move == "ir") and not item.action.drop
    )
    dropped = {item.action.drop for item in listed if item.action.drop}
    items = []
    for _, pid, week, rest in valued[:empty]:
        meta = state.players[pid]
        drop: Projection | None = None
        if room > 0:
            room -= 1
            spot = " Claim takes the open spot until you move him to IR."
        else:
            drop = drop_candidate(state, bench, named | dropped)
            spot = (
                f" Claim needs a spot before he moves to IR: {drop_reason(state, drop)}"
                if drop
                else " Roster full; no bench player can be dropped yet."
            )
        if drop:
            dropped.add(drop.player_id)
        items.append(
            Item(
                "stash",
                Action(
                    kind="waiver",
                    urgency="later",
                    title=f"Stash {meta.name} on IR" + (f", drop {drop.name}" if drop else ""),
                    # His form before the injury is his evidence line's, said there once.
                    reason=f"Back wk {week}; {rest:.1f} proj pts through wk {final}.{spot}",
                    player_id=pid,
                    drop=drop.player_id if drop else "",
                    evidence=_evidence(state, meta),
                    key=f"stash:{pid}",
                ),
            )
        )
    return items


def _form(state: Week, player_id: str) -> float | None:
    """His points a game over his last few games played, before he was hurt; None with too few to say."""
    role = state.evidence.roles.get(player_id)
    return role.points if role is not None and role.games >= MIN_GAMES_FOR_AVERAGE else None


def _evidence(state: Week, meta: PlayerInfo) -> list[Stat]:
    """How he was used before he was hurt, and his latest headlines."""
    role = state.evidence.roles.get(meta.player_id)
    lines = [Stat(label=meta.name, value=role.describe())] if role else []
    return lines + headlines(state, [meta])
