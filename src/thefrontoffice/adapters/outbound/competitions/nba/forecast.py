"""This week's basketball matchup as the simulation reads it: what is on the board, and the games still to come.

The generic engine in `application/forecasting.py` plays it out; this says
what a basketball week is made of. Each player's games are his last fifteen,
drawn one at a time for every game his club has left that he would start: a
lineup is set day by day, so on a night more of a roster plays than it has
active slots, only the best of them count. A player ruled out plays none until
the day ESPN expects him back. What a side has already scored is Yahoo's,
straight off the scoreboard.

A points league sums each game under the league's weights; a category league
keeps the whole box score of each game, so the stats that rise together —
points, threes, shots — still do in the simulation.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    INJURED_SLOTS,
    Category,
    amount,
    fantasy_points,
    line,
    printed,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.week import BENCH
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, Pairing, StatCategory, YahooPlayer
from thefrontoffice.domain.errors import UnsupportedError
from thefrontoffice.domain.models import CategoryMatchup, MatchupInput, Outcomes, ScoredCategory, StatLines

logger = logging.getLogger(__name__)

RANKING_WEIGHTS = {"12": 1.0, "15": 1.2, "16": 1.5, "17": 3.0, "18": 3.0, "19": -1.0}
"""Yahoo's default points scoring, by stat id: in a category league, one rough worth per player to
say who starts on a night more of a roster plays than it has slots for."""

FORM_ERROR = 0.1
"""Spread of a factor on a player's whole week in a points league, for how far his last fifteen games
may be off the week to come — a new role, a coach's rotation — beyond how they varied among themselves."""

PERCENT_PLACES = 3
"""Yahoo prints a percentage '.478', and two sides level to three places tie the category."""

Games = Callable[[YahooPlayer], list[NBAGameLog]]
"""A player's recent games, newest first: none for one Sleeper cannot place."""


@dataclass(frozen=True)
class Week:
    """What the rest of a week turns on, for both sides alike: who has played lately, who plays when, who is back."""

    games: Games
    left: Sequence[ScheduledGame]
    """The real games still to tip off this week."""

    returns: Mapping[str, date]
    """The day ESPN expects each injured player back, by Yahoo key."""

    weekly: bool = False
    """Lineups are set once for the week (`LeagueSettings.weekly_lineups`): today's starters play every game."""

    seed: int = 0


def points(
    found: Pairing,
    mine: Sequence[YahooPlayer],
    theirs: Sequence[YahooPlayer],
    week: Week,
    weights: Mapping[str, float],
) -> MatchupInput:
    """A points week: each side's fantasy points so far, plus every game its players have left, summed under `weights`.

    Raises:
        UnsupportedError: the league weights a stat a box score here does not count.
    """
    slots = active_slots(mine, theirs)

    def side(score: MatchupSide, roster: Sequence[YahooPlayer]) -> tuple[Outcomes, ...]:
        sampled = {p.player_key: _scored(week.games(p), weights) for p in roster}
        counts = starts(roster, week, slots, {key: _mean(s) for key, s in sampled.items()})
        board = amount(score.points)
        return (
            Outcomes(f"board:{score.team_key}", score.name, board, (), floor=board, games=0),
            *(
                Outcomes(
                    p.player_key,
                    p.name,
                    _mean(sampled[p.player_key]) * counts.get(p.player_key, 0),
                    tuple(sampled[p.player_key]),
                    projection_error=FORM_ERROR,
                    games=counts.get(p.player_key, 0),
                )
                for p in roster
                if counts.get(p.player_key) and sampled[p.player_key]
            ),
        )

    return MatchupInput(mine=side(found.mine, mine), theirs=side(found.opponent, theirs), seed=week.seed)


def categories(
    found: Pairing,
    mine: Sequence[YahooPlayer],
    theirs: Sequence[YahooPlayer],
    week: Week,
    scored: Sequence[StatCategory],
) -> MatchupInput:
    """A category week: each side's totals so far, plus every game its players have left, box score by box score.

    Raises:
        UnsupportedError: the league scores a category this app cannot build from a box score.
    """
    known = {c.yahoo_stat: c for c in CATEGORIES}
    unknown = [c.name for c in scored if c.stat_id not in known]
    if unknown:
        raise UnsupportedError("This league", f"a forecast of a week scored on {', '.join(unknown)}")
    used = [known[c.stat_id] for c in scored]
    stats = tuple(dict.fromkeys(key for c in used for key in (c.made, c.attempts) if key))
    slots = active_slots(mine, theirs)

    def side(roster: Sequence[YahooPlayer]) -> tuple[StatLines, ...]:
        played = {p.player_key: week.games(p) for p in roster}
        worth = {key: _mean(_scored(logs, RANKING_WEIGHTS)) for key, logs in played.items()}
        counts = starts(roster, week, slots, worth)
        return tuple(
            StatLines(
                p.player_key,
                tuple(tuple(g.get(stat) for stat in stats) for g in played[p.player_key]),
                counts[p.player_key],
            )
            for p in roster
            if counts.get(p.player_key) and played[p.player_key]
        )

    return MatchupInput(
        mine=(),
        theirs=(),
        seed=week.seed,
        categories=CategoryMatchup(
            stats=stats,
            categories=tuple(
                ScoredCategory(
                    name=c.name,
                    made=known[c.stat_id].made,
                    attempts=known[c.stat_id].attempts,
                    fewer_wins=c.fewer_wins,
                    places=PERCENT_PLACES if known[c.stat_id].is_percentage else None,
                )
                for c in scored
            ),
            mine=side(mine),
            theirs=side(theirs),
            board_mine=board(found.mine, used, stats),
            board_theirs=board(found.opponent, used, stats),
        ),
    )


def board(side: MatchupSide, used: Sequence[Category], stats: Sequence[str]) -> tuple[float, ...]:
    """One side's totals so far, in `stats` order, from the figures Yahoo prints: a percentage's from its makes over attempts.

    A figure not yet printed — a dash before the first game — is nothing scored.
    """
    totals: dict[str, float] = {}
    for category in used:
        made, taken = printed(side.stats, category)
        totals[category.made] = made
        if category.is_percentage:
            totals[category.attempts] = taken
    return tuple(totals.get(stat, 0.0) for stat in stats)


def active_slots(*rosters: Sequence[YahooPlayer]) -> int:
    """How many players a side starts on a night: the most active slots either roster fills today.

    Read off the rosters, which every league sets the same way; a slot left
    empty on both is one nobody is counted in.
    """
    return max((sum(1 for p in roster if _active(p)) for roster in rosters), default=0)


def _active(player: YahooPlayer) -> bool:
    """Whether he is in today's lineup: slotted, and neither benched nor on an injured slot."""
    return bool(player.slot) and player.slot != BENCH and player.slot not in INJURED_SLOTS


def starts(roster: Sequence[YahooPlayer], week: Week, slots: int, worth: Mapping[str, float]) -> dict[str, int]:
    """How many of the games left each player would start, by Yahoo key: on each night, the best `slots` who play.

    Nobody on an injured slot plays, and nobody ruled out until the day ESPN
    expects him back. Where lineups are set for the week, today's starters
    play every game they have and nobody else any; where no roster fills a
    slot today, every player who plays counts.
    """
    nights: dict[date, set[str]] = {}
    for game in week.left:
        day = parse_day(game.date)
        if day is not None:
            nights.setdefault(day, set()).update(club.upper() for club in (game.home, game.away) if club)
    counts: dict[str, int] = {}
    able = [p for p in roster if _active(p)] if week.weekly else [p for p in roster if p.slot not in INJURED_SLOTS]
    cap = 0 if week.weekly else slots
    for day, clubs in sorted(nights.items()):
        playing = [p for p in able if p.team.upper() in clubs and _available(p, day, week.returns)]
        playing.sort(key=lambda p: worth.get(p.player_key, 0.0), reverse=True)
        for player in playing[: cap or len(playing)]:
            counts[player.player_key] = counts.get(player.player_key, 0) + 1
    return counts


def _available(player: YahooPlayer, day: date, returns: Mapping[str, date]) -> bool:
    """Whether he can play on `day`: not ruled out, or ruled out with ESPN expecting him back by then."""
    if not ruled_out(player.status):
        return True
    back = returns.get(player.player_key)
    return back is not None and back <= day


def _scored(games: Sequence[NBAGameLog], weights: Mapping[str, float]) -> list[float]:
    """Each game's fantasy points under `weights`.

    Raises:
        UnsupportedError: `weights` names a stat a box score here does not count.
    """
    scored = []
    for game in games:
        value = fantasy_points(line(game.stats), weights)
        if value is None:
            raise UnsupportedError("This league", "a forecast of points weighting a stat no box score here counts")
        scored.append(value)
    return scored


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
