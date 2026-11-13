"""The trades worth offering: one or two of yours for one of theirs, near even in worth.

A trade nobody will accept is not advice, so the search starts from what
makes one acceptable: what they get is worth near what they give, each player
priced by his points over the best of his position on the waiver wire. A
manager still chasing a playoff place also wants his starters to come out
ahead, and which managers are still chasing one is the season engine's to
say, so each trade carries what it does to their starters and leaves that
judgment there.

What a trade is worth to you is in two parts: the regular season left, which
the season engine plays out for your playoff chance, and the playoff weeks
themselves, which no simulation of the table reaches. A team already safe
trades for those.

Two for one where one alone is not enough: depth given up for a better
starter, the deal a deadline is made of. The roster spot it frees is named,
with the free agent who would help your lineup most in it, but not counted in
the trade's worth: a spot is one a drop could open anyway, so crediting the
pickup to the trade would price a waiver move as if only the trade allowed it.
"""

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations

from thefrontoffice.adapters.outbound.competitions.nfl.league import SeasonModel, last_week, season_model
from thefrontoffice.adapters.outbound.competitions.nfl.model import NFLSource, Projection, Team, active
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS, STREAMED
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.domain.models import TeamWeek, TradeMarket, TradeOption

logger = logging.getLogger(__name__)

FAIR_SHARE = 0.8
"""The least of what they give, in points over the waiver wire, that they must get back: a gap a
better lineup can talk a manager into, and no wider."""


@dataclass(frozen=True)
class _Weeks:
    """The weeks a trade changes: the regular season left after this one, and the playoffs."""

    regular: list[int]
    playoffs: list[int]

    @property
    def every(self) -> list[int]:
        return self.regular + self.playoffs


def build(client: NFLSource, state: Week, seed: int) -> TradeMarket | None:
    """The season, and every trade near even in worth that improves your lineup; None once trading is over.

    A trade lands after the league's review, so it changes the weeks after
    this one: this week's lineups are already set.
    """
    deadline = state.league.trade_deadline
    if deadline and state.week > deadline:
        return None
    model = season_model(client, state, seed)
    if model is None:
        return None
    mine = next((r for r in model.rosters if r.roster_id == state.roster.roster_id), None)
    regular = [week for week in model.projections if week > state.week]
    if not regular or mine is None:
        return None

    model, weeks = _with_playoffs(client, state, model, regular)
    worth = _over_the_wire(model, weeks.every)
    pickup = _pickup(model, state, weeks)
    options: list[TradeOption] = []
    for theirs in model.rosters:
        if theirs.roster_id != mine.roster_id:
            options += _with(model, state, weeks, worth, pickup, mine, theirs)
    logger.info(f"Found {len(options)} trades near even in worth that help your lineup")
    return TradeMarket(season=model.season, options=tuple(options))


def _with_playoffs(
    client: NFLSource, state: Week, model: SeasonModel, regular: list[int]
) -> tuple[SeasonModel, _Weeks]:
    """The model with the playoff weeks' projections added, where the platform has published them."""
    league = state.league
    playoffs: dict[int, Mapping[str, Projection]] = {}
    for week in range(league.playoff_week_start, last_week(state) + 1):
        projections = client.get_projections(
            state.season, week, league.scoring_format, FANTASY_POSITIONS, league.scoring_rules
        )
        # A week nobody has projected yet would price every trade at nothing.
        if projections:
            playoffs[week] = projections
    model = replace(model, projections={**model.projections, **playoffs})
    return model, _Weeks(regular=regular, playoffs=list(playoffs))


def _with(
    model: SeasonModel,
    state: Week,
    weeks: _Weeks,
    worth: Callable[[str], float],
    pickup: Callable[[list[str], int], str],
    mine: Team,
    theirs: Team,
) -> list[TradeOption]:
    """Every trade with this team that improves your lineup and is near even in worth, best for you first."""
    mean = _cached(model, state)

    def per_week(ids: Iterable[str], over: Sequence[int]) -> float:
        held = frozenset(ids)
        return sum(mean(held, week) for week in over) / len(over) if over else 0.0

    my_ids, their_ids = _tradeable(mine, state), _tradeable(theirs, state)
    # Each lineup from who can start in it: a reserve or taxi player stays where he is.
    my_held, their_held = active(mine), active(theirs)
    my_now, their_now = per_week(my_held, weeks.every), per_week(their_held, weeks.every)
    my_regular, my_playoffs = per_week(my_held, weeks.regular), per_week(my_held, weeks.playoffs)
    # Losing a player never helps a lineup, so a trade can only help you if
    # what you get improves it on its own; that alone prunes most of theirs.
    wanted = [pid for pid in their_ids if per_week([*my_held, pid], weeks.every) > my_now]

    options = []
    for get in wanted:
        for give in _offers(my_ids, worth, worth(get)):
            mine_after = [pid for pid in my_held if pid not in give] + [get]
            if per_week(mine_after, weeks.every) <= my_now:
                continue
            theirs_after = [pid for pid in their_held if pid != get] + list(give)
            options.append(
                TradeOption(
                    team_id=str(theirs.roster_id),
                    giving=tuple(_label(pid, state) for pid in give),
                    receiving=(_label(get, state),),
                    points=per_week(mine_after, weeks.regular) - my_regular,
                    their_points=per_week(theirs_after, weeks.every) - their_now,
                    playoff_points=per_week(mine_after, weeks.playoffs) - my_playoffs if weeks.playoffs else None,
                    pickup=_label(added, state) if (added := pickup(mine_after, len(give) - 1)) else "",
                    scoring=tuple(
                        TeamWeek(
                            team_id=str(roster.roster_id),
                            week=week,
                            mean=mean(frozenset(ids), week),
                            spread=model.spread,
                        )
                        for roster, ids in ((mine, mine_after), (theirs, theirs_after))
                        for week in weeks.regular
                    ),
                )
            )
    return sorted(options, key=lambda option: -(option.playoff_points or option.points))


def _cached(model: SeasonModel, state: Week) -> Callable[[frozenset[str], int], float]:
    """`model.mean`, kept per roster and week: the search asks the same lineup again and again."""
    seen: dict[tuple[frozenset[str], int], float] = {}

    def mean(ids: frozenset[str], week: int) -> float:
        if (ids, week) not in seen:
            # Sorted, so a tie in the lineup breaks the same way whatever the set's order.
            seen[ids, week] = model.mean(state, sorted(ids), week)
        return seen[ids, week]

    return mean


def _offers(my_ids: list[str], worth: Callable[[str], float], asked: float) -> list[tuple[str, ...]]:
    """What you could give for a player worth `asked`: one who is enough alone, or two where neither is.

    Two where one would do is a player thrown away, so a pair is offered only
    when it takes both to come near what is asked.
    """
    enough = FAIR_SHARE * asked
    alone: list[tuple[str, ...]] = [(pid,) for pid in my_ids if worth(pid) >= enough]
    short = [pid for pid in my_ids if 0 < worth(pid) < enough]
    pairs: list[tuple[str, ...]] = [p for p in combinations(short, 2) if worth(p[0]) + worth(p[1]) >= enough]
    return alone + pairs


def _pickup(model: SeasonModel, state: Week, weeks: _Weeks) -> Callable[[list[str], int], str]:
    """Names the free agent who would help a lineup most in the roster spots a trade frees, if any would.

    The best free agent at each position is tried, and named only if he
    improves the lineup.
    """
    rostered = {pid for roster in model.rosters for pid in roster.player_ids}
    totals: dict[str, float] = {}
    positions: dict[str, str] = {}
    for week in weeks.every:
        for pid, projection in model.projections[week].items():
            if pid not in rostered and projection.position not in STREAMED:
                totals[pid] = totals.get(pid, 0.0) + projection.points
                positions[pid] = projection.position
    best: dict[str, str] = {}
    for pid, total in totals.items():
        if total > totals.get(best.get(positions[pid], ""), 0.0):
            best[positions[pid]] = pid
    candidates = list(best.values())
    mean = _cached(model, state)

    def score(ids: Iterable[str]) -> float:
        held = frozenset(ids)
        return sum(mean(held, week) for week in weeks.every)

    def fill(after: list[str], freed: int) -> str:
        if freed < 1 or not candidates:
            return ""
        top = max(candidates, key=lambda pid: score([*after, pid]))
        return top if score([*after, top]) > score(after) else ""

    return fill


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
    return [pid for pid in active(roster) if not ((meta := state.players.get(pid)) and meta.position in STREAMED)]


def _label(player_id: str, state: Week) -> str:
    meta = state.players.get(player_id)
    if meta is None:
        return player_id
    return f"{meta.name} ({meta.position})" if meta.position else meta.name
