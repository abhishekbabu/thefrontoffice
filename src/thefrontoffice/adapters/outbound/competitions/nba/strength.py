"""A basketball roster's week to come, as the season and its trades read it: the games its lineups start, and
what they add up to.

Each night a lineup starts the best of the players whose clubs play, no more
than its slots (`started`); where lineups are set for the week, the best for
the week play every game they have. A week is then each player's games times
what a game of him gives (`Profile`): a points league's fantasy points, or a
category league's box score — counting categories summed, a percentage as
makes over attempts.

Each figure carries its spread (`Uncertainty`, fitted to a season played: see
`FITTED`), so two sides' weeks give a chance of one taking a category from the
other (`category_chances`): normal on the difference, which a week of
thirty-odd games is near enough to. A week won on the most categories is then
the chance of taking more than half of them (`week_chances`) — not as if each
were a coin of its own: a week a roster plays more than expected lifts its
points, rebounds, threes and turnovers together, so the categories swing as
one more often than independent coins would.
"""

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES
from thefrontoffice.adapters.outbound.competitions.nba.model import LeagueCategory, Player, WeekSide
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    Category,
    Line,
    amount,
    fantasy_points,
    line,
    playable_from,
    printed,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.domain.errors import UnsupportedError

POINTS = "points"
"""The one figure a points league's week is: its fantasy points."""


@dataclass(frozen=True)
class Uncertainty:
    """How far a week may stray from what its games add up to, beyond each game's own swing — by label: a
    counting category, a percentage, or a points league's `POINTS`."""

    missed: float
    """The share of his club's games a player sits out unforeseen — a rest night, a knock, a coach's call — which
    a schedule cannot show weeks ahead: his week expects that much less, and swings with which games he misses."""

    form: Mapping[str, float]
    """Spread of a factor on a player's whole week in a count, for how far his last fifteen games may be off the
    week to come — a new role, a hot or cold run — beyond how they varied among themselves."""

    rate: Mapping[str, float]
    """The same for a percentage's makes, as a share of them: a percentage moves far less than a count."""

    game: Mapping[str, float]
    """How far one game strays from his average, as a share of it, where he has too few games to measure."""

    typical: Mapping[str, float] = field(default_factory=dict)
    """A rostered player's game: each count's average, each percentage's rate, a points league's points."""

    kept: Mapping[str, float] = field(default_factory=dict)
    """The share of how far a player's line sits from `typical` that his weeks bear out: a line read off fifteen
    games and a projection is partly luck, and a week regresses it toward the typical player's. None kept in
    full."""

    loadings: Mapping[str, float] = field(default_factory=dict)
    """How strongly each category's margin moves with the one swing they share (`week_chances`), more of it
    better; none takes the categories as independent."""

    discounted: bool = True
    """Whether a week's figures expect the games he will miss; the hand-set spreads before `FITTED` did not."""

    def expected(self, label: str, figure: float) -> float:
        """What a week bears out of a line's `figure` — a game's count, or a percentage's rate."""
        if label not in self.kept:
            return figure
        typical = self.typical.get(label, 0.0)
        return typical + self.kept[label] * (figure - typical)


FITTED = Uncertainty(
    missed=0.115,
    form={POINTS: 0.22, "PTS": 0.24, "REB": 0.22, "AST": 0.28, "STL": 0.31, "BLK": 0.38, "3PTM": 0.29, "TO": 0.27},
    rate={"FG%": 0.015, "FT%": 0.055},
    game={POINTS: 0.31, "PTS": 0.39, "REB": 0.40, "AST": 0.49, "STL": 0.90, "BLK": 1.02, "3PTM": 0.69, "TO": 0.64},
    typical={
        POINTS: 31.0,
        "PTS": 15.47,
        "REB": 5.94,
        "AST": 3.56,
        "STL": 1.03,
        "BLK": 0.61,
        "3PTM": 1.66,
        "FG%": 0.477,
        "FT%": 0.793,
        "TO": 1.87,
    },
    kept={
        POINTS: 0.98,
        "PTS": 1.0,
        "REB": 0.91,
        "AST": 1.03,
        "STL": 0.79,
        "BLK": 0.93,
        "3PTM": 0.99,
        "FG%": 0.84,
        "FT%": 0.77,
        "TO": 0.92,
    },
    loadings={
        "PTS": 0.94,
        "REB": 0.63,
        "AST": 0.61,
        "STL": 0.43,
        "BLK": 0.30,
        "3PTM": 0.61,
        "FG%": 0.23,
        "FT%": 0.06,
        "TO": 0.54,
    },
)
"""Fitted by `just calibrate-nba` (`nba/tuning.py`) on Sleeper's box scores and projections of the 2025-26
regular season: 3,744 player-weeks over 24 Monday-to-Sunday weeks, each week's best 156 players (twelve rosters
of thirteen) by their line — his last fifteen games beside Sleeper's projection a game — who were fit to play it.
Each spread makes the variance a week projects match the squared misses, summed over every player-week as a
roster sums its players; the loadings are the one factor that best explains how those misses moved together.
Checked on leagues dealt from the 2026-27 weeks it never saw, it called categories at a Brier score of 0.188
against the hand-set spreads' 0.193, and weeks at 0.206 against 0.213: a "95%" category came in 93%, not 88%."""


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


def scored(categories: Sequence[LeagueCategory]) -> tuple[Scored, ...]:
    """The league's categories as this compares them.

    Raises:
        UnsupportedError: the league scores a category no box score here counts.
    """
    known = {c.yahoo_stat: c for c in CATEGORIES}
    unknown = [c.name for c in categories if c.stat_id not in known]
    if unknown:
        raise UnsupportedError("This league", f"a season scored on {', '.join(unknown)}")
    return tuple(Scored(known[c.stat_id].label, c.fewer_wins, known[c.stat_id].is_percentage) for c in categories)


def profile(
    reading: Reading,
    games: Sequence[NBAGameLog],
    weights: Mapping[str, float] | None,
    uncertainty: Uncertainty = FITTED,
) -> Profile:
    """A player's `Profile` from his reading — his form beside his projection — and his last games for the spread.

    A points league's game is his fantasy points nudged by his minutes, as his
    worth is; a category league's is his line (`line_profile`).
    """
    value = game_value(reading) or 0.0
    if weights is None:
        return line_profile(value, reading.line or {}, games, uncertainty)
    return points_profile(value, games, weights, uncertainty)


def points_profile(
    value: float, games: Sequence[NBAGameLog], weights: Mapping[str, float], uncertainty: Uncertainty = FITTED
) -> Profile:
    """A points league's game of a player worth `value` fantasy points, varying as his last `games` did."""
    lines = [line(g.stats) for g in games]
    nights = [p for figures in lines if (p := fantasy_points(figures, weights)) is not None]
    if len(lines) >= MIN_FORM_GAMES and len(nights) == len(lines):
        variance = statistics.pvariance(nights)
    else:
        variance = (uncertainty.game.get(POINTS, 0.0) * value) ** 2
    return Profile(value=value, mean={POINTS: value}, variance={POINTS: variance})


def line_profile(
    value: float, figures: Line, games: Sequence[NBAGameLog], uncertainty: Uncertainty = FITTED
) -> Profile:
    """A category league's game of a player worth `value`: his line `figures`, its counts varying as his last
    `games` did, its percentages weighed by the attempts he has been taking."""
    lines = [line(g.stats) for g in games]
    measured = len(lines) >= MIN_FORM_GAMES
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
            share = uncertainty.game.get(category.label, 0.0)
            variance[category.label] = statistics.pvariance(own) if measured else (share * figures[category.label]) ** 2
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


def nights(player: Player, games: Iterable[ScheduledGame], back: date | None) -> list[date]:
    """The nights he can play among `games`: his club's; while ruled out, only those from his return, if any;
    on waivers, only those from the day he clears them (`rules.playable_from`)."""
    days = club_nights(player.team, games)
    claimed = playable_from(player)
    if claimed is not None:
        days = [day for day in days if day >= claimed]
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


def week_totals(
    counts: Mapping[str, int], profiles: Mapping[str, Profile], uncertainty: Uncertainty = FITTED
) -> Totals:
    """A side's week: each player's games times what a game of him gives, summed — less the games he will miss
    unforeseen (`Uncertainty.missed`), and his line drawn toward the typical player's as far as weeks bear it out
    (`Uncertainty.kept`).

    Its variance is each game's; whether he plays it; and his form (`Uncertainty.form`) — a factor on his whole
    week, for how far his recent games may be off the week to come — or, on a percentage's makes, its own
    (`Uncertainty.rate`), since his attempts would move with them.
    """
    missed = uncertainty.missed
    plays = 1 - missed if uncertainty.discounted else 1.0
    mean: dict[str, float] = {}
    variance: dict[str, float] = {}
    attempts: dict[str, float] = {}
    for key, games in counts.items():
        found = profiles.get(key)
        if found is None:
            continue
        for label, value in found.mean.items():
            if label in found.attempts:
                taken = found.attempts[label]
                game = uncertainty.expected(label, value / taken) * taken if taken else 0.0
                expected = games * plays * game
                unforeseen = (uncertainty.rate.get(label, 0.0) * expected) ** 2
            else:
                game = uncertainty.expected(label, value)
                expected = games * plays * game
                unforeseen = (uncertainty.form.get(label, 0.0) * expected) ** 2 + games * missed * (
                    1 - missed
                ) * game**2
            mean[label] = mean.get(label, 0.0) + expected
            variance[label] = variance.get(label, 0.0) + games * plays * found.variance.get(label, 0.0) + unforeseen
        for label, value in found.attempts.items():
            attempts[label] = attempts.get(label, 0.0) + games * plays * value
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


MOST_TOGETHER = 0.95
"""The strongest a category may move with the shared swing: at one it would have no swing of its own left."""


def loadings(categories: Iterable[Scored], uncertainty: Uncertainty = FITTED) -> tuple[float, ...]:
    """How strongly winning each category moves with the swing they share, in the order given: turned for a
    category won by less, since a big week that lifts the rest lifts its turnovers too."""
    return tuple((-1.0 if c.fewer_wins else 1.0) * uncertainty.loadings.get(c.label, 0.0) for c in categories)


def hermite(n: int) -> list[tuple[float, float]]:
    """`n` points and weights that integrate a smooth function of a standard normal draw: the Gauss–Hermite
    rule, its roots found by Newton's method from the usual first guesses, rescaled from `exp(-x²)` to the
    normal's density."""
    roots: list[float] = []
    found: list[tuple[float, float]] = []
    z = 0.0
    for i in range((n + 1) // 2):
        if i == 0:
            z = math.sqrt(2 * n + 1) - 1.85575 * (2 * n + 1) ** -0.16667
        elif i == 1:
            z -= 1.14 * n**0.426 / z
        elif i == 2:
            z = 1.86 * z - 0.86 * roots[0]
        elif i == 3:
            z = 1.91 * z - 0.91 * roots[1]
        else:
            z = 2 * z - roots[i - 2]
        slope = 1.0
        for _ in range(100):
            value, previous = math.pi**-0.25, 0.0
            for j in range(1, n + 1):
                value, previous = z * math.sqrt(2 / j) * value - math.sqrt((j - 1) / j) * previous, value
            slope = math.sqrt(2 * n) * previous
            step = value / slope
            z -= step
            if abs(step) < 1e-14:
                break
        roots.append(z)
        weight = 2 / slope**2 / math.sqrt(math.pi)
        found.append((z * math.sqrt(2), weight))
        if 2 * i + 1 != n:
            found.append((-z * math.sqrt(2), weight))
    return sorted(found)


SWINGS = hermite(12)
"""Levels of the swing a week's categories share, each with its weight (`week_chances`): past ten a week's
chance moves by under a tenth of a point."""


def week_chances(chances: Sequence[float], together: Sequence[float] = ()) -> tuple[float, float]:
    """Your chance of taking more of these categories than they do, and theirs; a level split is the rest.

    `together` are the categories' `loadings`: a week's margins share one swing — whose roster plays more, or
    shoots hotter — and each moves with it that strongly, the rest of it its own. Read at each level of that
    swing, the categories are independent, and how many you take is worked out exactly, then weighed over the
    levels. With no loadings the categories are independent outright.
    """
    if not any(together):
        return _split(chances)
    normal = NormalDist()
    leads = [normal.inv_cdf(p) if 0.0 < p < 1.0 else None for p in chances]
    win = loss = 0.0
    for swing, weight in SWINGS:
        given = [
            p if lead is None else _below((lead + load * swing) / math.sqrt(1 - load**2))
            for p, lead, load in zip(chances, leads, _padded(together, len(chances)), strict=True)
        ]
        taken, lost = _split(given)
        win += weight * taken
        loss += weight * lost
    return win, loss


def _padded(together: Sequence[float], n: int) -> list[float]:
    found = [max(-MOST_TOGETHER, min(MOST_TOGETHER, load)) for load in together[:n]]
    return found + [0.0] * (n - len(found))


def _below(z: float) -> float:
    """The standard normal's chance of falling below `z`."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _split(chances: Sequence[float]) -> tuple[float, float]:
    """Your chance of taking more than half of these independent categories, and theirs: how many you take is
    the sum of independent chances, worked out exactly rather than drawn."""
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


def banked(side: WeekSide, categories: Sequence[Scored], *, points: bool) -> Totals:
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
