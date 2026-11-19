"""A basketball roster's week to come, as the season and its trades read it: the games its lineups start, and
what they add up to.

Each night a lineup starts the best of the players whose clubs play, no more
than its slots (`started`); where lineups are set for the week, the best for
the week play every game they have. A week is then each player's games times
what a game of him gives (`Profile`): a points league's fantasy points, or a
category league's box score — counting categories summed, a percentage as
makes over attempts.

Each figure carries its spread, so two sides' weeks give a chance of one
taking a category from the other (`category_chances`): normal on the
difference, which a week of thirty-odd games is near enough to. A week won on
the most categories is then the chance of taking more than half of them
(`week_chances`), the categories taken as independent — the stats that rise
together, points and threes, are the one thing this gives away against the
matchup forecast's box-score draws, which are too slow to repeat for every
trade.
"""

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.nba.forecast import FORM_ERROR
from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    Category,
    amount,
    fantasy_points,
    line,
    printed,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, StatCategory, YahooPlayer
from thefrontoffice.domain.errors import UnsupportedError

POINTS = "points"
"""The one figure a points league's week is: its fantasy points."""

GAME_SPREAD = 0.4
"""How far one game of a player strays from his average, as a share of it, where he has too few games of his own
to measure: a twenty-point scorer's nights run from about twelve to twenty-eight."""

MISSED = 0.1
"""The share of his club's games a player sits out unforeseen — a rest night, a knock, a coach's call — which
a schedule cannot show weeks ahead, and which moves a week's counts as much as his form does."""

RATE_ERROR = 0.03
"""How far a player's shooting over a week may sit off his recent rate beyond its own luck, as a share of it:
a 47% shooter's form is 45.6 to 48.4 — a percentage moves far less than a count does."""

ATTEMPTS = {"FG%": 10.0, "FT%": 3.0}
"""Shots a game a percentage is weighed by, for a player whose own attempts are unknown: a rotation player's."""


@dataclass(frozen=True)
class Profile:
    """What one game of a player gives, and how much it varies: the figures a week of him adds up."""

    value: float
    """A game of him in the league's scoring (`worth.game_value`): who starts on a crowded night, and his price."""

    mean: Mapping[str, float] = field(default_factory=dict)
    """A game's figures by label: each counting category, a percentage's makes, or a points league's `POINTS`."""

    variance: Mapping[str, float] = field(default_factory=dict)
    attempts: Mapping[str, float] = field(default_factory=dict)
    """A game's attempts, by percentage label."""


@dataclass(frozen=True)
class Totals:
    """A side's week in each figure it is judged on: expected totals, their variance, a percentage's attempts."""

    mean: Mapping[str, float] = field(default_factory=dict)
    variance: Mapping[str, float] = field(default_factory=dict)
    attempts: Mapping[str, float] = field(default_factory=dict)

    def plus(self, banked: Totals) -> Totals:
        """These totals with what is already banked added: certain, so it adds no variance."""
        return Totals(
            mean=_summed(self.mean, banked.mean),
            variance=self.variance,
            attempts=_summed(self.attempts, banked.attempts),
        )


@dataclass(frozen=True)
class Scored:
    """One category a league scores, as a week's totals are compared in it."""

    label: str
    fewer_wins: bool = False
    percentage: bool = False


def scored(categories: Sequence[StatCategory]) -> tuple[Scored, ...]:
    """The league's categories as this compares them.

    Raises:
        UnsupportedError: the league scores a category no box score here counts.
    """
    known = {c.yahoo_stat: c for c in CATEGORIES}
    unknown = [c.name for c in categories if c.stat_id not in known]
    if unknown:
        raise UnsupportedError("This league", f"a season scored on {', '.join(unknown)}")
    return tuple(Scored(known[c.stat_id].label, c.fewer_wins, known[c.stat_id].is_percentage) for c in categories)


def profile(reading: Reading, games: Sequence[NBAGameLog], weights: Mapping[str, float] | None) -> Profile:
    """A player's `Profile` from his reading — his form beside his projection — and his last games for the spread.

    A points league's game is his fantasy points nudged by his minutes, as his
    worth is; a category league's is his line, its percentages weighed by the
    attempts he has been taking.
    """
    value = game_value(reading) or 0.0
    lines = [line(g.stats) for g in games]
    measured = len(lines) >= MIN_FORM_GAMES
    if weights is not None:
        mean = value
        nights = [p for figures in lines if (p := fantasy_points(figures, weights)) is not None]
        spread = statistics.pstdev(nights) if measured and len(nights) == len(lines) else GAME_SPREAD * mean
        return Profile(value=value, mean={POINTS: mean}, variance={POINTS: spread**2})
    figures = reading.line or {}
    means: dict[str, float] = {}
    variance: dict[str, float] = {}
    attempts: dict[str, float] = {}
    for category in CATEGORIES:
        if category.label not in figures:
            continue
        if category.is_percentage:
            taken = _attempts(category, games)
            rate = figures[category.label]
            attempts[category.label] = taken
            means[category.label] = rate * taken
            # Makes out of attempts: a coin with his rate, flipped as often as he shoots.
            variance[category.label] = rate * (1 - rate) * taken
        else:
            means[category.label] = figures[category.label]
            own = [f.get(category.label, 0.0) for f in lines]
            variance[category.label] = (
                statistics.pvariance(own) if measured else (GAME_SPREAD * figures[category.label]) ** 2
            )
    return Profile(value=value, mean=means, variance=variance, attempts=attempts)


def _attempts(category: Category, games: Sequence[NBAGameLog]) -> float:
    """His attempts a game at a percentage over his last games, or a rotation player's without them."""
    if len(games) < MIN_FORM_GAMES:
        return ATTEMPTS.get(category.label, 0.0)
    return statistics.fmean(g.get(category.attempts) for g in games)


def club_nights(club: str, games: Iterable[ScheduledGame]) -> list[date]:
    """The nights `club` plays among `games`."""
    club = club.upper()
    return [day for g in games if club in (g.home.upper(), g.away.upper()) and (day := parse_day(g.date)) is not None]


def nights(player: YahooPlayer, games: Iterable[ScheduledGame], back: date | None) -> list[date]:
    """The nights he can play among `games`: his club's; while ruled out, only those from his return, if any."""
    days = club_nights(player.team, games)
    if not ruled_out(player.status):
        return days
    return [day for day in days if back is not None and day >= back]


def started(
    order: Sequence[str], days: Mapping[str, frozenset[date]], slots: int, *, weekly: bool = False
) -> dict[str, int]:
    """How many games each player starts in a week, by key: each night, the first `slots` of `order` who play.

    `order` is the roster best first; `days` the nights each can play. Where
    lineups are set for the week, the first `slots` who play at all that week
    play every game they have. No slots at all starts everybody who plays.
    """
    if weekly:
        ranked = sorted(order, key=lambda key: (len(days.get(key, ())) == 0, order.index(key)))
        chosen = ranked[:slots] if slots else ranked
        return {key: n for key in chosen if (n := len(days.get(key, ())))}
    filled: dict[date, int] = {}
    counts: dict[str, int] = {}
    for key in order:
        for night in days.get(key, ()):
            if slots and filled.get(night, 0) >= slots:
                continue
            filled[night] = filled.get(night, 0) + 1
            counts[key] = counts.get(key, 0) + 1
    return counts


def week_totals(counts: Mapping[str, int], profiles: Mapping[str, Profile]) -> Totals:
    """A side's week: each player's games times what a game of him gives, summed.

    Its variance is each game's, each player's form on top (`forecast.FORM_ERROR`) — a factor on his whole
    week, for how far his recent games may be off the week to come; `RATE_ERROR` on a percentage's makes, whose
    attempts that factor would move with them — and the games he may sit out unforeseen (`MISSED`).
    """
    mean: dict[str, float] = {}
    variance: dict[str, float] = {}
    attempts: dict[str, float] = {}
    for key, games in counts.items():
        found = profiles.get(key)
        if found is None:
            continue
        for label, value in found.mean.items():
            mean[label] = mean.get(label, 0.0) + games * value
            if label in found.attempts:
                unforeseen = (RATE_ERROR * games * value) ** 2
            else:
                unforeseen = (FORM_ERROR * games * value) ** 2 + games * MISSED * (1 - MISSED) * value**2
            variance[label] = variance.get(label, 0.0) + games * found.variance.get(label, 0.0) + unforeseen
        for label, value in found.attempts.items():
            attempts[label] = attempts.get(label, 0.0) + games * value
    return Totals(mean=mean, variance=variance, attempts=attempts)


def points_spread(totals: Totals) -> float:
    """How far a points week may stray from its mean."""
    return math.sqrt(totals.variance.get(POINTS, 0.0))


def category_chances(mine: Totals, theirs: Totals, categories: Iterable[Scored]) -> list[float]:
    """Your chance of taking each category from them over the week, in the order given."""
    return [_chance(mine, theirs, category) for category in categories]


def _chance(mine: Totals, theirs: Totals, category: Scored) -> float:
    label = category.label
    if category.percentage:
        a_taken, b_taken = mine.attempts.get(label, 0.0), theirs.attempts.get(label, 0.0)
        if not a_taken or not b_taken:
            # Nobody shooting has no percentage, and loses the category to anybody who does.
            return 0.5 if a_taken == b_taken else float(a_taken > b_taken)
        lead = mine.mean.get(label, 0.0) / a_taken - theirs.mean.get(label, 0.0) / b_taken
        variance = mine.variance.get(label, 0.0) / a_taken**2 + theirs.variance.get(label, 0.0) / b_taken**2
    else:
        lead = mine.mean.get(label, 0.0) - theirs.mean.get(label, 0.0)
        variance = mine.variance.get(label, 0.0) + theirs.variance.get(label, 0.0)
    if category.fewer_wins:
        lead = -lead
    if variance <= 0:
        return 0.5 if lead == 0 else float(lead > 0)
    return 0.5 * (1 + math.erf(lead / math.sqrt(2 * variance)))


def week_chances(chances: Sequence[float]) -> tuple[float, float]:
    """Your chance of taking more of these categories than they do, and theirs; a level split is the rest.

    How many you take is the sum of independent chances, worked out exactly rather than drawn.
    """
    taken = [1.0]
    for chance in chances:
        taken = [
            (taken[n] if n < len(taken) else 0.0) * (1 - chance) + (taken[n - 1] * chance if n else 0.0)
            for n in range(len(taken) + 1)
        ]
    half = len(chances) / 2
    win = sum(p for n, p in enumerate(taken) if n > half)
    loss = sum(p for n, p in enumerate(taken) if n < half)
    return win, loss


def banked(side: MatchupSide, categories: Sequence[Scored], *, points: bool) -> Totals:
    """What a side has already scored this week, from the figures Yahoo prints: its fantasy points, or each
    category's total — a percentage's makes and attempts, from the '109/218' beside it.

    A figure not yet printed — a dash before the first game — is nothing scored.
    """
    if points:
        return Totals(mean={POINTS: amount(side.points)})
    by_label = {c.label: c for c in CATEGORIES}
    mean: dict[str, float] = {}
    attempts: dict[str, float] = {}
    for category in categories:
        made, taken = printed(side.stats, by_label[category.label])
        mean[category.label] = made
        if category.percentage:
            attempts[category.label] = taken
    return Totals(mean=mean, attempts=attempts)


def _summed(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, float]:
    return {label: a.get(label, 0.0) + b.get(label, 0.0) for label in {*a, *b}}
