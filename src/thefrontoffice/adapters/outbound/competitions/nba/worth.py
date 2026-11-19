"""What a basketball player is worth this week: what he gives a game, times the games he has left.

Every weekly decision weighs him by this one figure — who to start, who to
stream, who to drop — and the lineup rows and the prompt print the parts it is
made of, so the page, the to-do list and the model never rank him two ways.

A game's value is his recent form beside Sleeper's projection for the week
(`competitions.worth.blend`), category by category, read in the league's own
scoring: fantasy points under its weights, or his contribution across the
categories it scores (`category_value`). His minutes nudge it (`MINUTES`).
"""

import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions import worth as shared
from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES, PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES, Line, fantasy_points, line
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory, YahooLine, YahooPlayer


class MinutesRule(NamedTuple):
    games: int
    steady: float
    swing: float


MINUTES = MinutesRule(games=5, steady=30.0, swing=10.0)
"""How his minutes nudge his worth (`competitions.worth.usage`), over his last `games` games played.

30 or more in every one is a starter's steady role: a tenth more. Ten or more
between his most and least, without his latest game being his most, is a role
that comes and goes — a sixth man behind a returning starter, a big in foul
trouble, a rookie in and out: a tenth less. Basketball has no snap count, and
minutes are the share of the game a player is on the floor.
"""

Valuer = Callable[[Line], float | None]
"""What one game of a line is worth in a league's scoring."""


def points_value(weights: Mapping[str, float]) -> Valuer:
    """A points league's: fantasy points under its weights (`rules.fantasy_points`)."""
    return lambda figures: fantasy_points(figures, weights)


BY_STAT = {c.yahoo_stat: c for c in CATEGORIES}


@dataclass(frozen=True)
class Scale:
    """One category's spread across a pool, which a line's figure in it is read against."""

    scored: StatCategory
    """The category as the league names it: 'ST', where this app says 'STL'."""

    sign: float
    """-1 for a category won by less (turnovers), else 1."""

    centre: float
    """Where his figure is counted from: the pool's average for a percentage, nought for a count."""

    spread: float
    mean: float
    """The pool's average, which says whether his figure is weak for the pool."""


def scales(scored: Sequence[StatCategory], pool: Iterable[Line]) -> dict[str, Scale]:
    """Each category the league scores and this app has a figure for, by label, scaled across `pool`.

    A category with no spread across the pool (one line, or all alike) scales nothing and is left out.
    """
    lines = list(pool)
    found: dict[str, Scale] = {}
    for scored_as in scored:
        category = BY_STAT.get(scored_as.stat_id)
        if category is None:
            continue
        figures = [figures[category.label] for figures in lines if category.label in figures]
        spread = statistics.pstdev(figures) if len(figures) > 1 else 0.0
        if not spread:
            continue
        mean = statistics.fmean(figures)
        found[category.label] = Scale(
            scored=scored_as,
            sign=-1.0 if scored_as.fewer_wins else 1.0,
            centre=mean if category.is_percentage else 0.0,
            spread=spread,
            mean=mean,
        )
    return found


def category_value(scored: Sequence[StatCategory], pool: Iterable[Line]) -> Valuer:
    """A category league's: his contribution to each category it scores, in that category's spread across `pool`.

    A counting category is his figure over the pool's standard deviation, so a
    block weighs what the scarcity of blocks says and a point what the plenty
    of points says; a percentage is how far his rate sits above the pool's
    average, in the same units. Counting from nought rather than from the
    average keeps a game of anybody worth more than no game at all, which is
    what multiplying by games left needs. A category won by less (turnovers)
    counts against him. A category this app has no figure for (double-doubles)
    counts nothing, and percentages are not weighted by attempts.
    """
    found = scales(scored, pool)

    def value(figures: Line) -> float | None:
        if not figures or not found:
            return None
        return sum(
            scale.sign * (figures[label] - scale.centre) / scale.spread
            for label, scale in found.items()
            if label in figures
        )

    return value


WEAK_BELOW = -0.5
"""How far under the pool's average, in its spreads, a category must sit to be one he is weak in."""

WEAKEST = 2
"""The weak categories a player's note names: the two that drag his value most."""


def weakest(figures: Line | None, found: Mapping[str, Scale]) -> list[StatCategory]:
    """The categories he is weakest in against the pool, worst first, as the league names them: at most `WEAKEST`.

    Read against the pool's average rather than from nought, so a guard's few
    blocks read as the shortfall they are; only those under it by `WEAK_BELOW`
    of a spread, so an average line names none.
    """
    if not figures:
        return []
    below = {
        label: z
        for label, scale in found.items()
        if label in figures and (z := scale.sign * (figures[label] - scale.mean) / scale.spread) <= WEAK_BELOW
    }
    return [found[label].scored for label in sorted(below, key=lambda label: below[label])[:WEAKEST]]


def per_game(stats: PlayerStats | None, projected: ProjectedTotals | None) -> Line | None:
    """His line a game: his recent run beside Sleeper's projection a game this week, category by category.

    Either alone where the other is missing; None with neither.
    """
    recent = run.line if stats and (run := stats.get("recent")) else {}
    ahead = line(projected.totals, games=projected.games) if projected and projected.games else {}
    if not recent and not ahead:
        return None
    labels = dict.fromkeys([*recent, *ahead])
    return {
        label: value for label in labels if (value := shared.blend(recent.get(label), ahead.get(label))) is not None
    }


def minutes(stats: PlayerStats | None) -> tuple[float, ...]:
    """His minutes over his last `MINUTES.games` games, oldest first."""
    return tuple(reversed((stats or PlayerStats()).get("minutes", ())[: MINUTES.games]))


def usage(stats: PlayerStats | None) -> float:
    """What his minutes multiply his worth by (`MINUTES`)."""
    return shared.usage(minutes(stats), steady_from=MINUTES.steady, swings_by=MINUTES.swing, fewest=MIN_FORM_GAMES)


@dataclass(frozen=True)
class Reading:
    """One player's week, as every decision about him weighs it."""

    player: YahooPlayer
    line: Line | None
    """What he gives a game (`per_game`); None with no form and no projection."""

    per_game: float | None
    """That line in the league's scoring; None where it has no figure."""

    games: int | None
    """Games he can play before the week ends: his club's left, none while ruled out, from his return where
    one is reported. None where the schedule would not load."""

    usage: float = 1.0
    minutes: float | None = None
    """His minutes a game over his last few; None without them."""

    provisional: bool = False
    """Whether `games` is short of the week's: the NBA has days of it still to schedule (`week.unsettled`)."""

    back: date | None = None
    """The day ESPN expects him back, while it reports him hurt; None otherwise."""

    weak: tuple[StatCategory, ...] = ()
    """The categories that drag his value, worst first, as the league names them (`weakest`); none in a points
    league."""

    average: YahooLine | None = None
    """Yahoo's own average over his last month, the figures every view shows of him; None where not read.
    Shown, never weighed: the week is weighed on `line`, which Sleeper's box scores build game by game."""

    @property
    def worth(self) -> float | None:
        """`per_game` × `usage` × `games`: what he adds this week. None where either is unknown."""
        if self.per_game is None or self.games is None:
            return None
        return self.per_game * self.usage * self.games


def game_value(reading: Reading) -> float | None:
    """What a game of him is worth, nudged by his minutes: whether he is one to keep at all, whatever his week."""
    return None if reading.per_game is None else reading.per_game * reading.usage


def read(
    player: YahooPlayer,
    stats: PlayerStats | None,
    projected: ProjectedTotals | None,
    value: Valuer,
    games: int | None,
    provisional: bool = False,
    back: date | None = None,
) -> Reading:
    """One player's `Reading`, from his form, his projection, the games he can play (a floor where
    `provisional`) and when he is back."""
    figures = per_game(stats, projected)
    played = minutes(stats)
    return Reading(
        player=player,
        line=figures,
        per_game=value(figures) if figures else None,
        games=games,
        usage=usage(stats),
        minutes=statistics.fmean(played) if played else None,
        provisional=provisional,
        back=back,
    )
