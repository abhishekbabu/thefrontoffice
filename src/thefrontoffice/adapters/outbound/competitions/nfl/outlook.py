"""The next few weeks of your roster: which of them byes and injuries leave short, and the pickup that fixes it.

A week where three starters are out at once is a loss that can be seen from a
month away, and a waiver claim made then costs a bench spot; made the morning
of, it costs whatever is left. So each coming week is projected as the roster
stands — Sleeper publishes projections weeks ahead, byes included — and one
that falls well below the roster's usual week says so, names who is missing,
and names the free agent who closes most of the gap.
"""

import logging
import statistics
from collections.abc import Callable, Sequence

from thefrontoffice.adapters.outbound.competitions.nfl.actions import join
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import season_average
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupSlot, lineup_points
from thefrontoffice.adapters.outbound.competitions.nfl.model import NFLSource, Projection
from thefrontoffice.adapters.outbound.competitions.nfl.rules import LONG_TERM, SEASON_WEEKS
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week, games_by_week, lineup_for
from thefrontoffice.domain.models import Action, WeekAhead

logger = logging.getLogger(__name__)

WEEKS_AHEAD = 4
"""Far enough to see a bye cluster coming; further than that, projections are mostly a depth chart."""

SHORT_BY = 10.0
"""Points below the usual week that make one worth acting on: about a starter's worth."""

MIN_GAIN = 2.0
"""Points a pickup must add to the week to be worth a roster spot: less is a coin flip, not a fix."""

FIXES_TRIED = 40
"""Free agents tried for a short week, best projection first: past that the wire is nobody's start."""


def build(client: NFLSource, state: Week, league_id: str, signable: Callable[[str], bool]) -> list[WeekAhead]:
    """Each of the next weeks, soonest first, with a fix for any that is short.

    `signable` says whether a player could be added at all — on an NFL roster,
    at a position the league scores — which is the provider's rule, not this one's.
    """
    weeks = list(range(state.week + 1, min(state.week + WEEKS_AHEAD, SEASON_WEEKS) + 1))
    if not weeks:
        return []
    playing = {
        week: {club for game in games for club in (game.home, game.away)}
        for week, games in games_by_week(client, state.season).items()
    }
    owned = {pid for roster in client.get_rosters(league_id) for pid in roster.player_ids}
    held = [pid for pid in state.roster.player_ids if pid not in state.roster.reserve_ids]
    projections = {week: client.get_projections(state.season, week, state.league.scoring_format) for week in weeks}

    def lineup(ids: list[str], week: int) -> list[LineupSlot]:
        return lineup_for(state, [pid for pid in ids if not _ruled_out(pid, state)], projections[week])

    lineups = {week: lineup(held, week) for week in weeks}
    usual = statistics.median(lineup_points(slots) for slots in lineups.values())
    # A regular is somebody the best lineup uses in most of these weeks: who a
    # short week is short of, and who is never the one to drop.
    # Asked as if everyone were fit, so a starter ruled out for a while is still one of yours.
    healthy = [lineup_for(state, held, projections[week]) for week in weeks]
    starts = [slot.player.player_id for slots in healthy for slot in slots if slot.player]
    regulars = {pid for pid in set(starts) if starts.count(pid) * 2 >= len(weeks)}
    # Never the one to drop: a regular, or anyone the lineup leans on in one of these weeks.
    needed_soon = regulars | {slot.player.player_id for slots in lineups.values() for slot in slots if slot.player}

    ahead = []
    for week in weeks:
        points = lineup_points(lineups[week])
        # Asked of every regular rather than of those the lineup left out: a
        # quarterback on bye with nobody behind him still fills the slot, at nought.
        away = {
            pid: why for pid in held if pid in regulars and (why := _why(pid, state, week, playing.get(week, set())))
        }
        row = WeekAhead(
            week=week,
            points=points,
            usual=usual,
            missing=list(away.values()),
            short=points < usual - SHORT_BY,
        )
        if row.short:
            # Somebody for the positions the week is without, not a better
            # kicker: that is a different question, asked every week.
            needed = {str(state.players.get(pid, {}).get("position") or "") for pid in away}
            available = [
                p
                for pid, p in projections[week].items()
                if pid not in owned
                and p.position in needed
                and p.opponent
                and p.injury_status.upper() not in LONG_TERM
                and signable(pid)
            ]
            row = _fixed(
                row, state, held, available, lambda ids, week: lineup_points(lineup(ids, week)), needed_soon | set(away)
            )
        ahead.append(row)
    return ahead


def _ruled_out(player_id: str, state: Week) -> bool:
    """Whether his current ruling reaches into the weeks ahead: a long one does; a plain Out is for this week's game."""
    return str(state.players.get(player_id, {}).get("injury_status") or "").upper() in LONG_TERM


def _why(player_id: str, state: Week, week: int, playing: set[str]) -> str:
    """'Josh Allen (bye)': who, and why the lineup goes without him; empty where he is available."""
    meta = state.players.get(player_id, {})
    name = meta.get("name") or player_id
    if playing and meta.get("team") not in playing:
        return f"{name} (bye)"
    return f"{name} ({str(meta.get('injury_status')).lower()})" if _ruled_out(player_id, state) else ""


def _fixed(
    row: WeekAhead,
    state: Week,
    held: list[str],
    available: Sequence[Projection],
    best: Callable[[list[str], int], float],
    keep: set[str],
) -> WeekAhead:
    """The week with the free agent who adds most to it, and who makes room for him."""
    tried = sorted(available, key=lambda p: -p.points)[:FIXES_TRIED]
    gains = [(best([*held, p.player_id], row.week) - row.points, p) for p in tried]
    gain, pick = max(gains, key=lambda pair: pair[0], default=(0.0, None))
    if pick is None or gain < MIN_GAIN:
        return row
    fix = f"Pick up {pick.name} ({pick.position}, {pick.team}): {pick.points:.1f} projected in week {row.week}"
    if len(held) >= state.league.roster_spots:
        drop = _cheapest(state, held, keep)
        fix += f", drop {drop.name}" if drop else ""
    return row.model_copy(update={"fix": fix, "gain": round(gain, 1)})


def _cheapest(state: Week, held: list[str], keep: set[str]) -> Projection | None:
    """The player it costs least to lose: never a regular, nor one who is only away for the week."""
    candidates = [
        p
        for p in state.projected
        if p.player_id in held and p.player_id not in keep and p.player_id not in state.evidence.trends
    ]
    return min(candidates, key=lambda p: (season_average(state.evidence, p), p.points), default=None)


def to_do(ahead: list[WeekAhead], state: Week) -> Action | None:
    """Next week, as a to-do item, where byes and injuries leave it short: while a waiver run can still fix it.

    Only next week: the weeks after stay on My team, and next week is the one
    the to-do list can act on. It names the byes itself, so it stands in for
    that week's bye items rather than sitting beside them.
    """
    week = next((w for w in ahead if w.week == state.week + 1 and w.short), None)
    if week is None:
        return None
    without = f", without {join(week.missing)}" if week.missing else ""
    fix = (
        f" {week.fix}, +{week.gain:.1f}."
        if week.fix
        else " No free agent at those positions adds two points; a trade may: see My team."
    )
    return Action(
        kind="waiver" if week.fix else "trade",
        urgency="later",
        title=f"Week {week.week} is short",
        reason=f"Your best lineup projects {week.points:.1f} against {week.usual:.1f} in a usual week{without}.{fix}",
        when=f"week {week.week}",
        key=f"short:{week.week}",
    )
