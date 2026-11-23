"""The league's rosters as a week saw them: with its lineups, as they stood going into it, as they played it,
or as each would best line up for a week to come."""

import logging
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import replace

from thefrontoffice.adapters.outbound.competitions.nfl.lineup import optimal_lineup
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    PlayerInfo,
    Projection,
    active,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    pairings,
    projections_for,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    SleeperLeague,
    SleeperMatchup,
    SleeperRoster,
)
from thefrontoffice.domain.models import (
    outcome,
)

logger = logging.getLogger(__name__)


def with_lineups(rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup]) -> list[SleeperRoster]:
    """Every team, each starting the lineup it set for this week.

    A roster's own `starters` lags: Sleeper can keep serving the lineup as
    it stood days after the manager changed it, while the week's matchup
    already carries the new one. So the lineup is read from there, and
    from the roster only for a team with no matchup this week.
    """
    lineups = {entry.roster_id: entry.starters for entry in matchups if entry.starters}
    return [
        replace(roster, starter_ids=list(lineups[roster.roster_id])) if roster.roster_id in lineups else roster
        for roster in rosters
    ]


def banked(
    rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup], week: int, league: SleeperLeague
) -> list[SleeperRoster]:
    """The records with a finished week counted, where Sleeper has not counted it yet.

    Sleeper settles a week's results a day or so after its last game, and the
    page moves on before then: without this the table, and every simulation
    standing on it, would lose a week of wins. Whether Sleeper has counted it is
    read off the records themselves — a week each, two in a league that also
    plays its median — since they arrive in the same response that would carry it.
    A playoff week is never counted: the records are the regular season's.
    """
    per_week = 2 if league.median_game else 1
    if _in_playoffs(week, league) or any(r.wins + r.losses + r.ties >= week * per_week for r in rosters):
        return list(rosters)
    return _counted(rosters, matchups, league)


def as_of(
    rosters: Sequence[SleeperRoster], by_week: Mapping[int, Sequence[SleeperMatchup]], league: SleeperLeague
) -> list[SleeperRoster]:
    """The records as they stood going into a week: each of `by_week`'s results counted from none.

    What a week browsed back to is read against — its place in the table, the
    record beside each lineup — rather than the record the season has reached
    since. A playoff week is never counted, as in `banked`.
    """
    counted = [replace(r, wins=0, losses=0, ties=0, points_for=0.0) for r in rosters]
    for week, matchups in sorted(by_week.items()):
        if not _in_playoffs(week, league):
            counted = _counted(counted, matchups, league)
    return counted


def _in_playoffs(week: int, league: SleeperLeague) -> bool:
    return bool(league.playoff_week_start) and week >= league.playoff_week_start


def _counted(
    rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup], league: SleeperLeague
) -> list[SleeperRoster]:
    """Each record with one week's result added: its head-to-head, and its median game where the league plays one."""
    sides = {mine.roster_id: (mine, theirs) for a, b in pairings(matchups) for mine, theirs in ((a, b), (b, a))}
    scores = [entry.points for entry in matchups]
    middle = statistics.median(scores) if league.median_game and scores else None
    counted: list[SleeperRoster] = []
    for roster in rosters:
        side = sides.get(roster.roster_id)
        if side is None:
            counted.append(roster)
            continue
        mine, theirs = side
        results = [outcome(mine.points, theirs.points)]
        if middle is not None:
            results.append(outcome(mine.points, middle))
        counted.append(
            replace(
                roster,
                wins=roster.wins + results.count("won"),
                losses=roster.losses + results.count("lost"),
                ties=roster.ties + results.count("drawn"),
                points_for=round(roster.points_for + mine.points, 2),
            )
        )
    return counted


def as_played(rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup]) -> list[SleeperRoster]:
    """Every team holding who it held that week, which its matchup keeps after a drop or a trade.

    A team the week's matchups do not name keeps the roster it holds now.
    """
    held = {entry.roster_id: entry.players for entry in matchups if entry.players}
    return [
        replace(
            roster,
            player_ids=list(held[roster.roster_id]),
            reserve_ids=[pid for pid in roster.reserve_ids if pid in held[roster.roster_id]],
            ir_ids=[pid for pid in roster.ir_ids if pid in held[roster.roster_id]],
        )
        if roster.roster_id in held
        else roster
        for roster in rosters
    ]


def best_lineups(
    rosters: Sequence[SleeperRoster],
    slots: list[str],
    projections: Mapping[str, Projection],
    players: Mapping[str, PlayerInfo],
) -> list[SleeperRoster]:
    """Every team starting the best lineup its roster makes on these projections, slot by slot."""
    return [
        replace(
            roster,
            starter_ids=[
                slot.player.player_id if slot.player else ""
                for slot in optimal_lineup(slots, projections_for(active(roster), projections, players))
            ],
        )
        for roster in rosters
    ]
