"""What a basketball player is worth this week: what he gives a game, times the games he has left.

Every weekly decision weighs him by this one figure — who to start, who to
stream, who to drop — and the lineup rows and the prompt print the parts it is
made of, so the page, the to-do list and the model never rank him two ways.

A game's value is his recent form beside Sleeper's projection for the week
(`competitions.worth.blend`), category by category, read in the league's own
scoring: fantasy points under its weights, or his contribution across the
categories it scores (`category_value`). Where his minutes have moved, his
last few games pull it toward the role he plays now (`ROLE`), and his minutes
nudge it (`MINUTES`). Where his last few games ran well under or over his
projection, game after game (`streak`), he is weighed on that form instead.
"""

import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions import worth as shared
from thefrontoffice.adapters.outbound.competitions.availability import expected_games
from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES, ROLE_GAMES, PlayerStats, Role
from thefrontoffice.adapters.outbound.competitions.nba.model import LeagueCategory, Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    Line,
    amount,
    chance,
    fantasy_points,
    line,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.worth import HOT_LABEL, SLUMP_LABEL


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


TARGET_FLOOR = 0.1
"""The least a category counts this week, however sure it is: a forecast is not a result, and a lead can go.

A tenth, so a category all but won or lost barely moves a pickup: an add spent on it buys nothing this week.
`winnable` reaches it only below a 3% chance either way."""

IN_PLAY = 0.5
"""How winnable a category must be (`winnable`) to be one a move targets: a chance between about 15% and 85%."""

TARGETS = 3
"""The targeted categories a to-do item names: the three a move helps most."""


MATERIAL = 0.25
"""How far, in a category's spread, a pickup must move it over his drop for an item to name it: a quarter. Less is
a few tenths of a rebound, which a week of games swallows."""


def winnable(chance: float) -> float:
    """How much a category counts this week, from your chance of winning it: 1 at even, down to `TARGET_FLOOR`
    as it nears certain either way (4p(1 − p)). A category near 50/50 is the one a move can swing."""
    return max(TARGET_FLOOR, 4.0 * chance * (1.0 - chance))


@dataclass(frozen=True)
class Targeting:
    """This week's categories, each weighed by how winnable it is against the actual opponent (`winnable`).

    For the week's adds and drops only: what a player is worth for the rest of
    the season is opponent-neutral, so it never reads this.
    """

    scales: Mapping[str, Scale]
    """Each category's scale, by label: the pool the week is read across (`scales`)."""

    weights: Mapping[str, float]
    """How much each category counts this week, by label; one missing counts in full."""

    @classmethod
    def of(cls, found: Mapping[str, Scale], chances: Mapping[str, float]) -> Targeting:
        """From the forecast's chance of winning each category, by the league's name for it."""
        return cls(
            scales=found,
            weights={
                label: winnable(chances[scale.scored.name])
                for label, scale in found.items()
                if scale.scored.name in chances
            },
        )

    def value(self, figures: Line | None) -> float | None:
        """A game of `figures` this week: his contribution to each category, times how much it counts."""
        if not figures:
            return None
        parts = self._parts(figures)
        return sum(parts.values()) if parts else None

    def raised(self, pickup: Line | None, drop: Line | None, counting: float = IN_PLAY) -> list[str]:
        """The categories counting `counting` or more that a game of `pickup` really raises, as the league names
        them: by `MATERIAL` of a spread over one of `drop` — over the pool's average without one — and from a figure
        at least that average (`Scale.against_pool`). A centre's assists above a bigger centre's are still a
        centre's assists: no help to a roster short of them. At most `TARGETS`, the biggest gain first."""
        return self._moved(pickup, drop, counting, up=True)

    def lowered(self, pickup: Line | None, drop: Line | None, counting: float = IN_PLAY) -> list[str]:
        """The categories counting `counting` or more a game of `pickup` gives up by `MATERIAL` of a spread against
        one of `drop`, as the league names them: at most `TARGETS`, the biggest loss first. None without a drop."""
        return self._moved(pickup, drop, counting, up=False) if drop else []

    def _moved(self, pickup: Line | None, drop: Line | None, counting: float, *, up: bool) -> list[str]:
        if not pickup:
            return []
        moves: dict[str, float] = {}
        for label, scale in self.scales.items():
            mine = scale.against_pool(pickup)
            theirs = scale.against_pool(drop) if drop else 0.0
            if self.weights.get(label, 1.0) < counting or mine is None or theirs is None:
                continue
            change = mine - theirs if up else theirs - mine
            if change >= MATERIAL and (not up or mine >= 0):
                moves[label] = change
        ranked = sorted(moves, key=lambda label: -moves[label])[:TARGETS]
        return [self.scales[label].scored.name for label in ranked]

    def _parts(self, figures: Line) -> dict[str, float]:
        return {
            label: self.weights.get(label, 1.0) * worth
            for label, scale in self.scales.items()
            if (worth := scale.worth(figures)) is not None
        }


UNNEEDED = 0.7
"""What a category your roster is not short of counts for the rest of the season (`needs`): most of a game, so the
roster's needs tip a choice between keepers without making a specialist of every one."""


def needs(found: Mapping[str, Scale], standing: Mapping[str, float]) -> Targeting:
    """The categories weighed by what your roster lacks for the rest of the season, opponent-neutral.

    `standing` is how far your roster sits from its reference in each category,
    by label, in spreads, more being better (`league_standing`, or `pool_standing`
    without one): the `TARGETS` furthest below it count in full, every other one
    `UNNEEDED`. What a keeper adds there is what the season needs from him,
    whatever this week's opponent.
    """
    short = sorted((label for label, z in standing.items() if z < 0), key=lambda label: standing[label])[:TARGETS]
    return Targeting(scales=found, weights={label: 1.0 if label in short else UNNEEDED for label in found})


def pool_standing(found: Mapping[str, Scale], roster: Iterable[Line | None]) -> dict[str, float]:
    """Your players' average against the pool the week is scaled over (`Scale.against_pool`), by label: the
    stand-in for the league's standings where they will not load."""
    lines = [figures for figures in roster if figures]
    return {
        label: statistics.fmean(figures)
        for label, scale in found.items()
        if (figures := [z for f in lines if (z := scale.against_pool(f)) is not None])
    }


MIN_TEAMS = 4
"""The fewest teams with season totals a category is ranked across: fewer is no table to stand in."""


def league_standing(
    found: Mapping[str, Scale], mine: Mapping[str, float], others: Sequence[Mapping[str, float]]
) -> dict[str, float]:
    """Where your season stands in each category against the league's teams, by label: how far from their
    average, in their spread, more being better — a count a game (`team_rates`), a percentage's rate. A category
    fewer than `MIN_TEAMS` teams carry, or with no spread among them, is left out.
    """
    standing: dict[str, float] = {}
    for label, scale in found.items():
        stat = scale.scored.stat_id
        figures = [team[stat] for team in [mine, *others] if stat in team]
        if stat not in mine or len(figures) < MIN_TEAMS or not (spread := statistics.pstdev(figures)):
            continue
        standing[label] = scale.sign * (mine[stat] - statistics.fmean(figures)) / spread
    return standing


def team_rates(season: Mapping[str, str], games: int) -> dict[str, float]:
    """A team's season totals as the standings print them, by stat id, a count over `games` played and a
    percentage as its rate: teams a few games apart then compare alike. Every count as printed without games."""
    found: dict[str, float] = {}
    for stat, figure in season.items():
        category = BY_STAT.get(stat)
        if category is None:
            continue
        value = amount(figure)
        found[stat] = value if category.is_percentage or not games else value / games
    return found


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


STREAK_GAMES = ROLE_GAMES
"""His last games played a streak is read over: five, about a week and a half of a club's games, so one bad night
is a fifth of it — and the run his last five already average."""

SHORT_OF = 0.6
"""The share of his projection's value a game his last games must fall under, on average and game by game, to be a
slump. A single game's value swings by about his projection either way — a 4-point night with four blocks is a good
one in categories — so a run averaging under three-fifths of it, his worst night left out, is not a projection
running cold. With that night out, none of the 119 players that week held one; 8 did with it, Ajay Mitchell's on
two good nights of five."""

HOT_OVER = 1.4
"""The share of his projection's value his last games must run over to be hot, his best night left out: the slump's
margin the other way. Myles Turner's 14.6 a game over 10.2 projected on 24 Nov 2026 was one 27-point night; the
other four average 12.7, under the 14.3 bar."""

SPARE = 1
"""The games of the four left, once his most telling night is out (`competitions.worth.sustained`), that may miss the
bar: three of the four must clear it, as NFL's weekly slump needs all but one of its games."""

HOT_MINUTES = 24.0
"""The minutes a game over the run a hot one needs, and a keeper (`actions.Weigh.keeper`): half the game. Under it a
big night is a bench player's garbage time or a starter's night off. Of the 8 runs in a Yahoo league's week on 24 Nov
2026 that held without their best night (17 with it), 3 were on 11.7 to 19.3 minutes; Alex Caruso, offered as a
keeper on no streak at all, played 20.6."""


@dataclass(frozen=True)
class Swing:
    """One category his streak shows in: his figure a game over it against his projection's."""

    category: LeagueCategory
    now: float
    usual: float

    def short(self) -> str:
        """'FG% .226, proj .470' or '1.2 BLK, proj 2.3'."""
        if BY_STAT[self.category.stat_id].is_percentage:
            return f"{self.category.name} {_rate(self.now)}, proj {_rate(self.usual)}"
        return f"{self.now:.1f} {self.category.name}, proj {self.usual:.1f}"


def _rate(value: float) -> str:
    return f"{value:.3f}".removeprefix("0")


@dataclass(frozen=True)
class Streak:
    """His last games running well under his projection (a slump) or well over it (hot): `streak`."""

    hot: bool
    games: int
    recent: float
    """His value a game over them, game by game."""
    usual: float
    """His projection's value a game."""
    line: Line
    """His line a game over them: what he is weighed on, beside the projection (`competitions.worth.call`)."""
    ahead: Line
    """Sleeper's projection a game this week."""
    swings: tuple[Swing, ...] = ()
    """The categories it shows in most, in a category league (`swings`); none in a points league."""

    @property
    def label(self) -> str:
        return HOT_LABEL if self.hot else SLUMP_LABEL

    def short(self) -> str:
        """'4.1/g over his last 5 vs 10.2 projected · FG% .226, proj .470'."""
        lead = f"{self.recent:.1f}/g over his last {self.games} vs {self.usual:.1f} projected"
        return " · ".join([lead, *(swing.short() for swing in self.swings)])


def backed(stats: PlayerStats | None, healthy: bool) -> bool:
    """Whether a hot run is his role's and not a night's: `HOT_MINUTES` a game or more over it, and no open
    injury report — a questionable or game-time call is open."""
    played = (stats or PlayerStats()).get("minutes", ())[:STREAK_GAMES]
    return healthy and bool(played) and statistics.fmean(played) >= HOT_MINUTES


SEASON_SETTLING = 10
"""The games a streak is weighed against for the rest of the season (`competitions.worth.settled`): his usual
reading — fifteen games beside a projection of the season — holds about ten games' worth, so his last five pull it a
third of the way (5 / 15). The week's call (`competitions.worth.CALL_FORM`, three quarters) reads the next few
games; a season's sixty-odd more regress toward who he has been, and five games at three to one made Ajay Mitchell,
projected 12.8, a drop."""


def season_line(stats: PlayerStats | None, projected: ProjectedTotals | None, called: Streak | None) -> Line | None:
    """His line a game for the rest of the season: his usual reading (`per_game`), pulled toward a streak's games by
    `settled(STREAK_GAMES, SEASON_SETTLING)`; the usual reading where there is no streak."""
    usual = per_game(stats, projected)
    if called is None or usual is None:
        return usual
    pull = shared.settled(called.games, SEASON_SETTLING)
    return {label: value + pull * (called.line.get(label, value) - value) for label, value in usual.items()}


def streak(stats: PlayerStats | None, projected: ProjectedTotals | None, value: Valuer) -> Streak | None:
    """His last `STREAK_GAMES` games against his projection, where they ran past it for long enough; None otherwise.

    A slump: his value a game under `SHORT_OF` of the projection's, on average and in all but `SPARE` of the games,
    his worst left out. Hot: over `HOT_OVER` of it, the same way, his best left out (`competitions.worth.sustained`);
    whether his minutes and health back it is `backed`'s to say. Read in the league's own scoring —
    across its categories in a category league, so a shooting collapse counts as the drag on his value it is —
    and only against a projection: his form alone has nothing to run past.
    """
    found = stats or PlayerStats()
    run, latest = found.get("run", ()), found.get("last_5")
    if len(run) < STREAK_GAMES or not latest or projected is None or not projected.games:
        return None
    ahead = line(projected.totals, games=projected.games)
    usual = value(ahead)
    scored = [figure for game in run if (figure := value(game)) is not None]
    if usual is None or usual <= 0 or len(scored) < len(run):
        return None
    for share, hot in ((SHORT_OF, False), (HOT_OVER, True)):
        if shared.sustained(scored, [usual] * len(scored), share, SPARE):
            return Streak(hot, len(run), statistics.fmean(scored), usual, latest, ahead)
    return None


SWUNG = 0.5
"""How far, in a category's spread across the pool, his figure over the streak must sit from his projection's for the
streak to name it: as far as a weak category sits under the pool (`WEAK_BELOW`)."""

SWINGS = 2
"""The categories a streak names: the two it shows in most."""


def swings(found: Streak | None, scaled: Mapping[str, Scale]) -> Streak | None:
    """`found` with the categories it shows in most, the way it ran: at most `SWINGS`, by `SWUNG` of a spread or more."""
    if found is None or not scaled:
        return found
    moved: dict[str, float] = {}
    for label, scale in scaled.items():
        now, usual = scale.against_pool(found.line), scale.against_pool(found.ahead)
        if now is not None and usual is not None and (change := now - usual if found.hot else usual - now) >= SWUNG:
            moved[label] = change
    ranked = sorted(moved, key=lambda label: -moved[label])[:SWINGS]
    named = tuple(Swing(scaled[label].scored, found.line[label], found.ahead[label]) for label in ranked)
    return replace(found, swings=named)


def moved(role: Role | None) -> bool:
    """Whether his minutes over his last few have moved from the window's by `ROLE.moved`, either way."""
    return role is not None and abs(role.minutes - role.window) >= ROLE.moved


def falling(role: Role | None) -> bool:
    """Whether his minutes over his last few have fallen below the window's by `ROLE.moved`: a role shrinking, the
    first a drop lets go."""
    return role is not None and role.window - role.minutes >= ROLE.moved


def rising(stats: PlayerStats | None) -> bool:
    """Whether his role is growing now: each of his last `ROLE.latest` games `ROLE.moved` minutes or more above
    the window's. One long night is not: an overtime game lifts one game, not two."""
    role = (stats or PlayerStats()).get("role")
    latest = (stats or PlayerStats()).get("minutes", ())[: ROLE.latest]
    return role is not None and len(latest) == ROLE.latest and min(latest) >= role.window + ROLE.moved


def per_game(stats: PlayerStats | None, projected: ProjectedTotals | None, called: Streak | None = None) -> Line | None:
    """His line a game: his recent run beside Sleeper's projection a game this week, category by category,
    pulled toward his last few games where his role has moved (`ROLE`) — or, on a streak (`called`), his last few
    games called against the projection (`competitions.worth.call`).

    Either alone where the other is missing; None with neither.
    """
    if called is not None:
        labels = dict.fromkeys([*called.line, *called.ahead])
        return {
            label: shared.call(called.line.get(label, ahead), ahead)
            for label in labels
            if (ahead := called.ahead.get(label, called.line.get(label))) is not None
        }
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

    streak: Streak | None = None
    """His last games run well under or over his projection (`streak`): what `line` is then called on."""

    missed: int = 0
    """Games his club has played in a row without him while the report gives no firm return (`reads.doubts`): his
    games are then not counted on a return; nought otherwise."""

    season: Line | None = None
    """His line a game for the rest of the season (`season_line`): what a keeper, or a player kept, is weighed on.
    None reads `line`."""

    season_value: float | None = None
    """That line in the league's scoring; None reads `per_game`."""

    unproven: bool = False
    """Whether his last games ran hot without the minutes or health to back them (`backed`): never a keeper."""

    talk: str = ""
    """The story his own news puts him in trade talk with, 'Fri 21 Nov: …' (`news.talked`); empty otherwise."""

    @property
    def held(self) -> Line | None:
        """His line a game for the rest of the season."""
        return self.season if self.season is not None else self.line

    @property
    def cold(self) -> bool:
        """Whether he is in a slump (`streak`)."""
        return self.streak is not None and not self.streak.hot

    @property
    def hot(self) -> bool:
        """Whether he is on a hot run (`streak`): never the player let go over a cold one."""
        return self.streak is not None and self.streak.hot

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
    """What a game of him is worth this week, nudged by his minutes."""
    return None if reading.per_game is None else reading.per_game * reading.usage


def kept_value(reading: Reading) -> float | None:
    """What a game of him is worth for the rest of the season, nudged by his minutes: whether he is one to keep at
    all, whatever his week (`season_line`)."""
    per = reading.season_value if reading.season_value is not None else reading.per_game
    return None if per is None else per * reading.usage


def read(
    player: Player,
    stats: PlayerStats | None,
    projected: ProjectedTotals | None,
    value: Valuer,
    games: int | None,
    provisional: bool = False,
    back: date | None = None,
    healthy: bool = True,
) -> Reading:
    """One player's `Reading`, from his form, his projection, the games he can play (a floor where
    `provisional`) and when he is back: this week on his recent form where it ran past his projection (`streak`),
    the season a third of the way toward it (`season_line`). A hot run his minutes or health — `healthy`, no injury
    reported — do not back (`backed`) is no streak, and marks him `unproven`."""
    called = streak(stats, projected, value)
    unproven = called is not None and called.hot and not backed(stats, healthy)
    if unproven:
        called = None
    figures = per_game(stats, projected, called)
    kept = season_line(stats, projected, called) if called is not None else None
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
        streak=called,
        season=kept,
        season_value=value(kept) if kept else None,
        unproven=unproven,
    )
