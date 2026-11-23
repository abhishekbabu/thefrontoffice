"""What a basketball player is worth this week: what he gives a game, times the games he has left.

Every weekly decision weighs him by this one figure — who to start, who to
stream, who to drop — and the lineup rows and the prompt print the parts it is
made of, so the page, the to-do list and the model never rank him two ways.

A game's value is his recent form beside Sleeper's projection for the week
(`competitions.worth.blend`), category by category, read in the league's own
scoring: fantasy points under its weights, or his contribution across the
categories it scores (`category_value`). Where his minutes have moved, his
last few games pull it toward the role he plays now (`ROLE`), and his minutes
nudge it (`MINUTES`).
"""

import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions import worth as shared
from thefrontoffice.adapters.outbound.competitions.availability import expected_games
from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES, PlayerStats, Role
from thefrontoffice.adapters.outbound.competitions.nba.model import LeagueCategory, Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    Line,
    chance,
    fantasy_points,
    line,
    ruled_out,
)


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


class RoleRule(NamedTuple):
    moved: float
    settling: int
    latest: int


ROLE = RoleRule(moved=3.0, settling=5, latest=2)
"""When his last few games outweigh the rest of his window (`form.Role`), and by how much.

His recent run is the window's half-life: a starter's minutes handed to a
bench player, or taken back from him, show in the last five games and are
averaged away over fifteen, while Sleeper's projection reads the season and is
slower still. So where his minutes a game over his last five differ from the
window's by `moved` or more — a tenth of a starter's — his line is pulled from
the usual reading toward those five games' by `worth.settled(5, settling)`: as
far as halfway, since five games of a new role are as often a hot week. A role
growing now — each of his `latest` games `moved` or more above the window's
minutes (`rising`) — pulls the same way before his last five average it in. With
his minutes where they were, a big night moves nothing beyond its share of the
average: points without the minutes behind them are not a role.
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

    scored: LeagueCategory
    """The category as the league names it: 'ST', where this app says 'STL'."""

    sign: float
    """-1 for a category won by less (turnovers), else 1."""

    spread: float
    """The pool's standard deviation: of the figure for a count, of the impact (`impact`) for a percentage."""

    mean: float
    """The pool's average figure: of a count, or its rate over all its attempts for a percentage."""

    def impact(self, figures: Line) -> float | None:
        """A percentage's pull on a team's rate: how far his rate sits from the pool's, times his attempts a game.

        2 for 3 and 10 for 15 are both .667, and only the second moves a team's
        FG% much. None for a count, or a line without the attempts to weigh it by.
        """
        category = BY_STAT[self.scored.stat_id]
        if not category.is_percentage or category.label not in figures or category.attempted not in figures:
            return None
        return (figures[category.label] - self.mean) * figures[category.attempted]

    def worth(self, figures: Line) -> float | None:
        """What his figure adds, in spreads: a count from nought, a percentage by its impact. None without one."""
        category = BY_STAT[self.scored.stat_id]
        figure = self.impact(figures) if category.is_percentage else figures.get(category.label)
        return None if figure is None else self.sign * figure / self.spread

    def against_pool(self, figures: Line) -> float | None:
        """How far his figure sits from the pool's average, in spreads; None without one."""
        category = BY_STAT[self.scored.stat_id]
        if category.is_percentage:
            return self.worth(figures)
        figure = figures.get(category.label)
        return None if figure is None else self.sign * (figure - self.mean) / self.spread


def scales(scored: Sequence[LeagueCategory], pool: Iterable[Line]) -> dict[str, Scale]:
    """Each category the league scores and this app has a figure for, by label, scaled across `pool`.

    A percentage's average is the pool's makes over its attempts — every
    attempt weighed alike, as a team's rate is built — and its spread is that
    of each line's impact (`Scale.impact`). A category with no spread across
    the pool (one line, or all alike) scales nothing and is left out.
    """
    lines = list(pool)
    found: dict[str, Scale] = {}
    for scored_as in scored:
        category = BY_STAT.get(scored_as.stat_id)
        if category is None:
            continue
        sign = -1.0 if scored_as.fewer_wins else 1.0
        if category.is_percentage:
            weighed = [f for f in lines if category.label in f and f.get(category.attempted)]
            tried = sum(f[category.attempted] for f in weighed)
            if not tried:
                continue
            mean = sum(f[category.label] * f[category.attempted] for f in weighed) / tried
            figures = [(f[category.label] - mean) * f[category.attempted] for f in weighed]
        else:
            figures = [f[category.label] for f in lines if category.label in f]
            mean = statistics.fmean(figures) if figures else 0.0
        spread = statistics.pstdev(figures) if len(figures) > 1 else 0.0
        if spread:
            found[category.label] = Scale(scored=scored_as, sign=sign, spread=spread, mean=mean)
    return found


def category_value(scored: Sequence[LeagueCategory], pool: Iterable[Line]) -> Valuer:
    """A category league's: his contribution to each category it scores, in that category's spread across `pool`.

    A counting category is his figure over the pool's standard deviation, so a
    block weighs what the scarcity of blocks says and a point what the plenty
    of points says. A percentage is his impact on a team's rate — how far his
    rate sits from the pool's, times his attempts — over the spread of that
    impact, so a big man going 3 for 4 a night does not outrank a scorer going
    9 for 18. Counting from nought rather than from the average keeps a game of
    anybody worth more than no game at all, which is what multiplying by games
    left needs. A category won by less (turnovers) counts against him. A
    category this app has no figure for (double-doubles) counts nothing.
    """
    found = scales(scored, pool)

    def value(figures: Line) -> float | None:
        if not figures or not found:
            return None
        return sum(worth for scale in found.values() if (worth := scale.worth(figures)) is not None)

    return value


WEAK_BELOW = -0.5
"""How far under the pool's average, in its spreads, a category must sit to be one he is weak in."""

WEAKEST = 2
"""The weak categories a player's note names: the two that drag his value most."""


def weakest(figures: Line | None, found: Mapping[str, Scale]) -> list[LeagueCategory]:
    """The categories he is weakest in against the pool, worst first, as the league names them: at most `WEAKEST`.

    Read against the pool's average rather than from nought, so a guard's few
    blocks read as the shortfall they are; only those under it by `WEAK_BELOW`
    of a spread, so an average line names none. A percentage reads by its
    impact, so a poor rate on few attempts is the small drag it is.
    """
    if not figures:
        return []
    below = {
        label: z for label, scale in found.items() if (z := scale.against_pool(figures)) is not None and z <= WEAK_BELOW
    }
    return [found[label].scored for label in sorted(below, key=lambda label: below[label])[:WEAKEST]]


def moved(role: Role | None) -> bool:
    """Whether his minutes over his last few have moved from the window's by `ROLE.moved`, either way."""
    return role is not None and abs(role.minutes - role.window) >= ROLE.moved


def rising(stats: PlayerStats | None) -> bool:
    """Whether his role is growing now: each of his last `ROLE.latest` games `ROLE.moved` minutes or more above
    the window's. One long night is not: an overtime game lifts one game, not two."""
    role = (stats or PlayerStats()).get("role")
    latest = (stats or PlayerStats()).get("minutes", ())[: ROLE.latest]
    return role is not None and len(latest) == ROLE.latest and min(latest) >= role.window + ROLE.moved


def per_game(stats: PlayerStats | None, projected: ProjectedTotals | None) -> Line | None:
    """His line a game: his recent run beside Sleeper's projection a game this week, category by category,
    pulled toward his last few games where his role has moved (`ROLE`).

    Either alone where the other is missing; None with neither.
    """
    recent = run.line if stats and (run := stats.get("recent")) else {}
    ahead = line(projected.totals, games=projected.games) if projected and projected.games else {}
    if not recent and not ahead:
        return None
    labels = dict.fromkeys([*recent, *ahead])
    usual = {
        label: value for label in labels if (value := shared.blend(recent.get(label), ahead.get(label))) is not None
    }
    role = (stats or PlayerStats()).get("role")
    latest = (stats or PlayerStats()).get("last_5")
    if role is None or not (moved(role) or rising(stats)) or not latest:
        return usual
    pull = shared.settled(role.games, ROLE.settling)
    return {label: value + pull * (latest.get(label, value) - value) for label, value in usual.items()}


def minutes(stats: PlayerStats | None) -> tuple[float, ...]:
    """His minutes over his last `MINUTES.games` games, oldest first."""
    return tuple(reversed((stats or PlayerStats()).get("minutes", ())[: MINUTES.games]))


def usage(stats: PlayerStats | None, hurt: bool = False) -> float:
    """What his minutes multiply his worth by (`MINUTES`).

    For a player ruled out now (`hurt`), a latest game that is his fewest
    minutes is the one he got hurt in: it is left out, since it says nothing
    of his role.
    """
    played = minutes(stats)
    if hurt and len(played) > 1 and played[-1] == min(played):
        played = tuple(reversed((stats or PlayerStats()).get("minutes", ())[1 : MINUTES.games + 1]))
    return shared.usage(played, steady_from=MINUTES.steady, swings_by=MINUTES.swing, fewest=MIN_FORM_GAMES)


@dataclass(frozen=True)
class Reading:
    """One player's week, as every decision about him weighs it."""

    player: Player
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

    weak: tuple[LeagueCategory, ...] = ()
    """The categories that drag his value, worst first, as the league names them (`weakest`); none in a points
    league."""

    average: PrintedLine | None = None
    """Yahoo's own average over his last month, the figures every view shows of him; None where not read.
    Shown, never weighed: the week is weighed on `line`, which Sleeper's box scores build game by game."""

    role: Role | None = None
    """His recent minutes against the window's (`form.Role`); None with too few games to compare."""

    rising: bool = False
    """Whether his minutes are growing now (`rising`): a role on its way up is never the one let go."""

    @property
    def worth(self) -> float | None:
        """`per_game` × `usage` × `games`: what he adds this week. None where either is unknown."""
        if self.per_game is None or self.games is None:
            return None
        return self.per_game * self.usage * self.games

    @property
    def available(self) -> float | None:
        """`worth` with a game-time decision's next game discounted (`rules.chance`): what picking him up is worth
        now. None where `worth` is."""
        if self.per_game is None or self.games is None:
            return None
        return self.per_game * self.usage * expected_games(self.games, chance(self.player.status))


def game_value(reading: Reading) -> float | None:
    """What a game of him is worth, nudged by his minutes: whether he is one to keep at all, whatever his week."""
    return None if reading.per_game is None else reading.per_game * reading.usage


def read(
    player: Player,
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
        usage=usage(stats, ruled_out(player.status)),
        minutes=statistics.fmean(played) if played else None,
        provisional=provisional,
        back=back,
        role=(stats or PlayerStats()).get("role"),
        rising=rising(stats),
    )
