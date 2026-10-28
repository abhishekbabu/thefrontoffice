"""The trades worth offering: one of yours for one of theirs, where both lineups come out ahead.

A trade nobody will accept is not advice, so the search starts from what
makes one acceptable — each side's starters projecting more for the rest of
the season than they do now, which is what a surplus at one position and a
hole at another looks like. Which of those is worth making is then the
season engine's question, answered in playoff chance rather than points: a
trade that strengthens the team you are chasing can cost more than it gains.

A better lineup is not the whole of a yes, though: a manager weighs what he
gives against what he gets, not only who starts on Sunday. So a trade is
offered only where what they get is worth near what they give, each player
priced by his points over the best of his position on the waiver wire.

One for one only. Two for one frees a roster spot nobody has priced, and a
pairing that only works as two for two is rarer than it is long to search.
"""

import logging
from collections.abc import Callable, Iterable

from thefrontoffice.adapters.outbound.competitions.nfl.league import SeasonModel, season_model
from thefrontoffice.adapters.outbound.competitions.nfl.model import NFLSource, Team
from thefrontoffice.adapters.outbound.competitions.nfl.rules import STREAMED
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.domain.models import TeamWeek, TradeMarket, TradeOption

logger = logging.getLogger(__name__)

TRADES_TRIED = 12
"""Trades played out against the season: the best by points, since each costs a simulation."""

TRADES_PER_TEAM = 3
"""So one manager's roster cannot fill the whole list with variations on a deal."""

MIN_THEIR_GAIN = 0.5
"""Points a week their starters must gain: the least that reads as a reason for them to say yes."""

FAIR_SHARE = 0.8
"""The least of what they give, in points over the waiver wire, that they must get back: a gap a
better lineup can talk a manager into, and no wider."""


def build(client: NFLSource, state: Week, league_id: str, seed: int) -> TradeMarket | None:
    """The season, and the trades that improve both lineups the most for you; None once trading is over.

    A trade lands after the league's review, so it changes the weeks after
    this one: this week's lineups are already set.
    """
    deadline = state.league.trade_deadline
    if deadline and state.week > deadline:
        return None
    model = season_model(client, state, league_id, seed)
    if model is None:
        return None
    weeks = [week for week in model.projections if week > state.week]
    mine = next((r for r in model.rosters if r.roster_id == state.roster.roster_id), None)
    if not weeks or mine is None:
        return None

    worth = _over_the_wire(model, weeks)
    options: list[TradeOption] = []
    for theirs in model.rosters:
        if theirs.roster_id != mine.roster_id:
            options += _with(model, state, weeks, worth, mine, theirs)[:TRADES_PER_TEAM]
    best = sorted(options, key=lambda option: -option.points)[:TRADES_TRIED]
    logger.info(f"Trying {len(best)} of {len(options)} trades that help both lineups")
    return TradeMarket(season=model.season, options=tuple(best))


def _with(
    model: SeasonModel, state: Week, weeks: list[int], worth: Callable[[str], float], mine: Team, theirs: Team
) -> list[TradeOption]:
    """Every one-for-one with this team that improves both lineups and is near even in worth, best for you first."""

    def per_week(ids: Iterable[str]) -> float:
        held = list(ids)
        return sum(model.mean(state, held, week) for week in weeks) / len(weeks)

    my_ids, their_ids = _tradeable(mine, state), _tradeable(theirs, state)
    my_now, their_now = per_week(mine.player_ids), per_week(theirs.player_ids)
    # Losing a player never helps a lineup, so a swap can only help a side whose
    # lineup the incoming player improves on his own; that alone prunes most pairs.
    wanted = [pid for pid in their_ids if per_week([*mine.player_ids, pid]) > my_now]
    sought = [pid for pid in my_ids if per_week([*theirs.player_ids, pid]) > their_now]

    options = []
    for give in sought:
        for get in wanted:
            mine_after = [pid for pid in mine.player_ids if pid != give] + [get]
            theirs_after = [pid for pid in theirs.player_ids if pid != get] + [give]
            gain, their_gain = per_week(mine_after) - my_now, per_week(theirs_after) - their_now
            if gain <= 0 or their_gain < MIN_THEIR_GAIN or worth(give) < FAIR_SHARE * worth(get):
                continue
            options.append(
                TradeOption(
                    team_id=str(theirs.roster_id),
                    giving=(_label(give, state),),
                    receiving=(_label(get, state),),
                    points=gain,
                    their_points=their_gain,
                    scoring=tuple(
                        TeamWeek(
                            team_id=str(roster.roster_id),
                            week=week,
                            mean=model.mean(state, ids, week),
                            spread=model.spread,
                        )
                        for roster, ids in ((mine, mine_after), (theirs, theirs_after))
                        for week in weeks
                    ),
                )
            )
    return sorted(options, key=lambda option: -option.points)


def _over_the_wire(model: SeasonModel, weeks: list[int]) -> Callable[[str], float]:
    """What a player is worth across these weeks: his projected points over the best free agent at his position.

    The wire is what a manager can have for nothing, so a player is worth only
    what he scores beyond it — a fourth quarterback, however good, is worth
    little to anyone.
    """
    rostered = {pid for roster in model.rosters for pid in roster.player_ids}
    wire: dict[tuple[int, str], float] = {}
    for week in weeks:
        for pid, projection in model.projections[week].items():
            if pid not in rostered:
                key = (week, projection.position)
                wire[key] = max(wire.get(key, 0.0), projection.points)

    def worth(player_id: str) -> float:
        total = 0.0
        for week in weeks:
            projection = model.projections[week].get(player_id)
            if projection:
                total += max(0.0, projection.points - wire.get((week, projection.position), 0.0))
        return total

    return worth


def _tradeable(roster: Team, state: Week) -> list[str]:
    """Players who could move: not those in injured reserve or taxi, whose slot would not follow them, nor a streamer."""
    return [
        pid
        for pid in roster.player_ids
        if pid not in roster.reserve_ids and state.players.get(pid, {}).get("position") not in STREAMED
    ]


def _label(player_id: str, state: Week) -> str:
    meta = state.players.get(player_id, {})
    name = meta.get("name") or player_id
    return f"{name} ({meta['position']})" if meta.get("position") else name
