"""The week weighed: each player's reading over a matchup week, the pool a category league is scaled
across, and the to-do list read off them.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from thefrontoffice.adapters.outbound.competitions.nba import actions
from thefrontoffice.adapters.outbound.competitions.nba import lineup as nba_lineup
from thefrontoffice.adapters.outbound.competitions.nba import worth as nba_worth
from thefrontoffice.adapters.outbound.competitions.nba.model import Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    PACIFIC,
    Line,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import reads
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.feeds import Feeds
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource, once
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Pairing,
    YahooLeague,
)
from thefrontoffice.domain.errors import (
    FrontOfficeError,
)
from thefrontoffice.domain.models import (
    Action,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decided:
    """The week weighed: every shown player's reading by Yahoo's key, and the to-do list read off them."""

    readings: dict[str, Reading]
    actions: list[Action]
    volume: tuple[int, int] | None = None
    """The games each side's lineups can start over the rest of the week: yours, then your opponent's."""


def decide(
    feeds: Feeds,
    yahoo: YahooSource,
    league: YahooLeague,
    roster: Sequence[Player],
    theirs: Sequence[Player],
    start: date,
    end: date,
    adds_left: int,
    also: Sequence[Player] | None = None,
    shown: Mapping[str, PrintedLine] | None = None,
) -> Decided:
    """Every shown player's week, and the to-do list weighed on it.

    Read over your roster, your opponent's and the wire, which is also the
    pool a category league's values are scaled across — the same pool for
    the page and the prompt, so both read one list. `also` are read on
    that same scale without joining the pool: the prompt's free agents.
    `shown` is Yahoo's averages for the rostered players, which every row and
    item shows of them; the wire carries its own.

    The wire is enrichment here: one that will not load (a sync that has not
    carried it) leaves the week's rows and starts standing, with nothing to stream.
    """
    try:
        free_agents = reads.wire(yahoo, reads.STREAM_DEPTH)
    except FrontOfficeError as e:
        logger.warning(f"Weighing the week without the wire, which would not load: {e}")
        free_agents = []
    weights = reads.weights(league, yahoo)
    averages = {**(shown or {}), **reads.carried(free_agents)}
    readings = read_week(feeds, yahoo, weights, [*roster, *theirs, *free_agents], start, end, also or [], averages)
    today = feeds.today(start, end)
    plan = plan_for(feeds, yahoo, (roster, theirs), free_agents, readings, weights, start, end)
    items = actions.build(roster, free_agents, readings, adds_left, weights is not None, today, plan)
    return Decided(readings, items, plan.volume)


def read_week(
    feeds: Feeds,
    yahoo: YahooSource,
    weights: Mapping[str, float] | None,
    players: Sequence[Player],
    start: date,
    end: date,
    also: Sequence[Player] | None = None,
    averages: Mapping[str, PrintedLine] | None = None,
) -> dict[str, Reading]:
    """Each of `players`' week between `start` and `end`, by Yahoo's key (`worth.read`), and `also`'s.

    Each carries Yahoo's average over his last month from `averages`, which
    is shown beside the week and never weighed in it.

    His games are his club's left, none while he is ruled out, or those from
    the day ESPN expects him back. A category league values a game across
    the categories it scores, scaled over `players` alone.
    """
    pool = {p.player_key for p in players}
    unique = list({p.player_key: p for p in [*players, *(also or [])]}.values())
    projections = index_for(feeds.sleeper, start, end)
    clubs = feeds.games.get_remaining_games_bulk([p.team for p in unique], start, end)
    returns = reads.returns(unique, feeds.reports())
    provisional = bool(feeds.games.unscheduled(start, end))
    stats = {p.player_key: feeds.form.get_player_stats(p.name) for p in unique}
    projected = {
        p.player_key: projections.find(p.name, p.team, stats[p.player_key]) if projections else None for p in unique
    }
    per_game = (
        nba_worth.per_game(stats[p.player_key], projected[p.player_key]) for p in unique if p.player_key in pool
    )
    value, found = reads.valuer(yahoo, weights, [line for line in per_game if line])
    readings = (
        nba_worth.read(
            p,
            stats[p.player_key],
            projected[p.player_key],
            value,
            feeds.playable(p, clubs, returns.get(p.player_key), end),
            provisional,
            returns.get(p.player_key),
        )
        for p in unique
    )
    shown = averages or {}
    return {
        r.player.player_key: replace(
            r, weak=tuple(nba_worth.weakest(r.line, found)), average=shown.get(r.player.player_key)
        )
        for r in readings
    }


def plan_for(
    feeds: Feeds,
    yahoo: YahooSource,
    sides: tuple[Sequence[Player], Sequence[Player]],
    free_agents: Sequence[Player],
    readings: Mapping[str, Reading],
    weights: Mapping[str, float] | None,
    start: date,
    end: date,
) -> actions.Plan:
    """What weighs a pickup beyond the readings (`actions.Plan`): the nights left and the lineup's slots,
    teammates due back, and the games each side can start.

    No week where the settings list no lineup slots, lineups are set for the
    week, or the schedule will not load: pickups are then weighed on every
    game their clubs have left.
    """
    roster, theirs = sides
    returning = feeds.returning(free_agents, [*roster, *theirs, *free_agents], weights)
    rules = yahoo.settings()
    slots = nba_lineup.slots(rules.slots)
    if not slots or rules.weekly_lineups:
        return actions.Plan(returning=returning)
    try:
        left = feeds.games.games_left(start, end)
    except FrontOfficeError as e:
        logger.warning(f"Weighing pickups on games left, without the nights: {e}")
        return actions.Plan(returning=returning)
    week = nba_lineup.Week(left, slots, datetime.now(PACIFIC).date(), end)
    backs = {key: r.back for key, r in readings.items()}
    volume = (nba_lineup.starts(roster, week, backs), nba_lineup.starts(theirs, week, backs))
    return actions.Plan(week=week, returning=returning, volume=volume)


def valued(
    feeds: Feeds,
    yahoo: YahooSource,
    league: YahooLeague,
    players: Sequence[Player],
    weights: Mapping[str, float] | None,
) -> dict[str, Reading]:
    """Each of `players`' week, a category league's read on the week's own scale: the pool the to-do list weighs,
    so a value reads alike.

    That pool is both rosters of this week's matchup and the top of the wire
    (`decide`); `players` are read on it without joining it. A points league's
    fantasy points need no scale, so `players` are their own pool. Enrichment:
    none between seasons, in a week without a matchup, or where a read fails —
    the table stands, its values dashed and in its own order.
    """
    week = league.current_week
    if not week:
        return {}
    try:
        team = yahoo.get_user_team()
        found = yahoo.pairing(team.team_key, week)
        if found is None:
            return {}
        if weights:
            return read_week(feeds, yahoo, weights, players, found.start, found.end)
        pool = [
            *yahoo.roster(team.team_key),
            *yahoo.roster(found.opponent.team_key),
            *reads.wire(yahoo, reads.STREAM_DEPTH),
        ]
        return read_week(feeds, yahoo, None, pool, found.start, found.end, players)
    except FrontOfficeError as e:
        logger.warning(f"Showing players without their value a game: {e}")
        return {}


def week_valuer(
    feeds: Feeds, yahoo: YahooSource, weights: Mapping[str, float] | None, found: Pairing
) -> nba_worth.Valuer | None:
    """What a game is worth on the week's scale: fantasy points, or a category league's value across the pool.

    The pool is the to-do list's (`decide`): both rosters of this week's
    matchup and the top of the wire, most of it read already by the page
    the drawer opened from. None where it will not load.
    """
    if weights:
        return nba_worth.points_value(weights)
    try:
        pool = [
            *yahoo.roster(found.mine.team_key),
            *yahoo.roster(found.opponent.team_key),
            *reads.wire(yahoo, reads.STREAM_DEPTH),
        ]
        projections = index_for(feeds.sleeper, found.start, found.end)
        lines: list[Line] = []
        for p in once(pool):
            stats = feeds.form.get_player_stats(p.name)
            projected = projections.find(p.name, p.team, stats) if projections else None
            if line := nba_worth.per_game(stats, projected):
                lines.append(line)
        return reads.valuer(yahoo, None, lines)[0]
    except FrontOfficeError as e:
        logger.warning(f"Showing the drawer without a value a game: {e}")
        return None
