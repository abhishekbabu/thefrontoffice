"""The spreads a basketball week is priced with (`strength.FITTED`), fitted to a season played and checked on
leagues dealt from it, as `just calibrate-nba` runs them.

Read from Sleeper's box scores and projections alone, so any season can be read
whole, not just the weeks one league has played. Each week of it, the
rostered-calibre players are the best `TEAMS` times `ROSTER` by their line —
their last fifteen games beside Sleeper's projection — among those fit to play:
three games of form, and in their club's last game before the week, which is as
near as box scores come to an injury report. A player-week is then one of them
projected as the app projects him, over his club's games that week, beside what
he did.

The fit (`fit`) reads each spread so a week's projected variance, summed over
every player-week, matches the squared misses summed the same way: a roster's
total is a sum of its players, so this is what a roster's week needs right. The
categories' misses, summed the same way, give their correlation, and the one
swing they share (`loadings`).

The check (`check`) deals each week's players into `LEAGUES` leagues of
`TEAMS` rosters at random, plays each roster's best on each night they play,
and scores every category and week the spreads called against what happened.
"""

import logging
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from thefrontoffice.adapters.outbound.competitions.nba.forecast import RANKING_WEIGHTS
from thefrontoffice.adapters.outbound.competitions.nba.form import (
    MIN_FORM_GAMES,
    RECENT_GAMES,
    SEASON_WEEKS,
    PlayerStats,
    RecentForm,
    nine_cat,
)
from thefrontoffice.adapters.outbound.competitions.nba.projections import aggregate
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES, TURNOVERS, Line, fantasy_points
from thefrontoffice.adapters.outbound.competitions.nba.strength import (
    FITTED,
    MOST_TOGETHER,
    POINTS,
    Profile,
    Scored,
    Totals,
    Uncertainty,
    category_chances,
    line_profile,
    loadings,
    points_profile,
    started,
    week_chances,
    week_totals,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import per_game
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNBASource, SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection, NBAGameLog
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import OddsCheck, OddsFit, OddsModel, calibration

logger = logging.getLogger(__name__)

TEAMS = 12
ROSTER = 13
SLOTS = 10
"""A standard Yahoo league: twelve rosters of thirteen, ten of them starting each night."""

LEAGUES = 20
"""Leagues dealt from each week's players in the check: enough that a season calls thousands of categories."""

PERCENT_PLACES = 3
"""Yahoo prints a percentage '.478', and two sides level to three places tie the category."""

COUNTS = tuple(c.label for c in CATEGORIES if not c.is_percentage)
PERCENTAGES = tuple(c.label for c in CATEGORIES if c.is_percentage)
LABELS = tuple(c.label for c in CATEGORIES)
NINE = tuple(Scored(c.label, fewer_wins=c is TURNOVERS, percentage=c.is_percentage) for c in CATEGORIES)
"""A nine-category league, as `strength` compares it."""

HAND_SET = Uncertainty(
    missed=0.1,
    form=dict.fromkeys((POINTS, *COUNTS), 0.1),
    rate=dict.fromkeys(PERCENTAGES, 0.03),
    game=dict.fromkeys((POINTS, *COUNTS), 0.4),
    discounted=False,
)
"""The spreads set by hand before any fit, kept to check the fit against: a tenth on a week's form, three
hundredths on a percentage, a tenth of games missed but not expected, and the categories independent."""

MODELS: dict[OddsModel, Uncertainty] = {
    "hand-set": HAND_SET,
    "fitted, independent": replace(FITTED, loadings={}),
    "fitted": FITTED,
}

WEEK = timedelta(days=7)

FACTOR_ROUNDS = 60
"""Rounds of principal-axis factoring (`one_factor`), and of power iteration in each: both settle in a few dozen."""


@dataclass(frozen=True)
class PlayerWeek:
    """One rostered-calibre player's week: what was known before it, and what he did."""

    key: str
    line: Line
    """What he gives a game as the app reads him (`worth.per_game`): his last fifteen games beside Sleeper's
    projection a game — the week before's, published before this one began, as a trade weeks ahead reads one."""

    value: float
    """That line in Yahoo's default points (`forecast.RANKING_WEIGHTS`): who is rostered, who starts."""

    form: tuple[NBAGameLog, ...]
    """His last fifteen games before the week, newest first: how his games vary."""

    nights: tuple[date, ...]
    """His club's games that week."""

    played: tuple[NBAGameLog, ...]
    """His games that week."""


def weeks_of(
    logs: Mapping[str, Sequence[NBAGameLog]], projected: Iterable[GameProjection] = ()
) -> list[list[PlayerWeek]]:
    """Each complete Monday-to-Sunday week of a season's box scores, as its rostered-calibre players' weeks,
    each read beside his `projected` games that week where Sleeper projected any.

    A club's games are the nights any of its players played. A week still being
    played, or before anyone has three games, has nobody in it and is left out.
    """
    games = {key: sorted(runs, key=lambda g: g.date) for key, runs in logs.items() if runs}
    ahead: dict[str, list[GameProjection]] = {}
    for row in projected:
        ahead.setdefault(row.player_id, []).append(row)
    clubs: dict[str, set[date]] = {}
    for runs in games.values():
        for game in runs:
            clubs.setdefault(game.team, set()).add(_day(game))
    nights = {club: sorted(days) for club, days in clubs.items()}
    days = sorted({day for club in nights.values() for day in club})
    if not days:
        return []
    weeks = []
    monday = days[0] - timedelta(days=days[0].weekday())
    while monday + WEEK - timedelta(days=1) <= days[-1]:
        end = monday + WEEK
        pool = [
            found
            for key, runs in games.items()
            if (found := _player_week(key, runs, ahead.get(key, ()), nights, (monday, end))) is not None
        ]
        pool.sort(key=lambda p: (-p.value, p.key))
        if pool:
            weeks.append(pool[: TEAMS * ROSTER])
        monday = end
    return weeks


def _player_week(
    key: str,
    runs: Sequence[NBAGameLog],
    ahead: Sequence[GameProjection],
    nights: Mapping[str, Sequence[date]],
    week: tuple[date, date],
) -> PlayerWeek | None:
    """His week, where he was fit to play it: three games of form, and in his club's last game before it."""
    monday, end = week
    before = [g for g in runs if _day(g) < monday]
    if len(before) < MIN_FORM_GAMES:
        return None
    last = before[-1]
    club = nights.get(last.team, [])
    previous = [day for day in club if day < monday]
    if not previous or previous[-1] != _day(last):
        return None
    played = tuple(g for g in runs if monday <= _day(g) < end)
    if any(g.team != last.team for g in played):
        return None  # traded that week: neither club's schedule is his
    form = tuple(reversed(before[-RECENT_GAMES:]))
    projected = aggregate(r for r in ahead if monday - WEEK <= date.fromisoformat(r.date[:10]) < monday)
    stats = PlayerStats(recent=RecentForm(games=len(form), line=nine_cat(list(form))))
    figures = per_game(stats, projected if projected.games else None) or {}
    return PlayerWeek(
        key=key,
        line=figures,
        value=fantasy_points(figures, RANKING_WEIGHTS) or 0.0,
        form=form,
        nights=tuple(day for day in club if monday <= day < end),
        played=played,
    )


def _day(game: NBAGameLog) -> date:
    return date.fromisoformat(game.date[:10])


# ── the fit ─────────────────────────────────────────────────────────────


def fit(season: str, weeks: Sequence[Sequence[PlayerWeek]]) -> OddsFit:
    """The spreads that make `weeks`' projected variance match their squared misses, category by category.

    First the share of games missed; then the typical player's game, and how
    much of a player's distance from it his weeks bore out — the slope of what he
    did on what was projected, both measured from the typical player. Then each
    spread, which enters a week's variance squared (`strength.week_totals`): the
    variance projected with every spread at nought, and again at one, says how
    much each adds, and the fit is the share that closes the gap.

    Raises:
        NotFoundError: no player-week to fit on.
    """
    samples = [week for weeks_in in weeks for week in weeks_in]
    scheduled = sum(len(p.nights) for p in samples)
    if not scheduled:
        raise NotFoundError(f"a week of the {season} season to fit odds on")
    missed = 1 - sum(len(p.played) for p in samples) / scheduled
    labels = (POINTS, *LABELS)
    profiles = [_profile(p, HAND_SET) for p in samples]
    actuals = [_actual(p.played) for p in samples]
    typical = _typical(samples, profiles)
    kept = _kept(samples, profiles, actuals, typical, 1 - missed)
    bare = Uncertainty(missed=missed, form={}, rate={}, game={}, typical=typical, kept=kept)
    unit = replace(bare, form=dict.fromkeys(labels, 1.0), rate=dict.fromkeys(labels, 1.0))
    squared = dict.fromkeys(labels, 0.0)
    base = dict.fromkeys(labels, 0.0)
    added = dict.fromkeys(labels, 0.0)
    own = dict.fromkeys(labels, 0.0)
    level = dict.fromkeys(labels, 0.0)
    misses: list[dict[str, float]] = []
    for player, profile, actual in zip(samples, profiles, actuals, strict=True):
        without, with_unit = (_week_of(player, profile, spreads) for spreads in (bare, unit))
        miss = _misses(without, actual)
        misses.append(miss)
        for label in labels:
            squared[label] += miss.get(label, 0.0) ** 2
            base[label] += without.variance.get(label, 0.0)
            added[label] += with_unit.variance.get(label, 0.0) - without.variance.get(label, 0.0)
            if label not in profile.attempts:
                own[label] += profile.variance.get(label, 0.0)
                level[label] += profile.mean.get(label, 0.0) ** 2
    spreads = {
        label: math.sqrt(max(0.0, squared[label] - base[label]) / added[label]) for label in labels if added[label]
    }
    correlation = _correlation(misses, LABELS)
    return OddsFit(
        season=season,
        player_weeks=len(samples),
        missed=missed,
        form={label: spreads[label] for label in (POINTS, *COUNTS) if label in spreads},
        rate={label: spreads[label] for label in PERCENTAGES if label in spreads},
        game={label: math.sqrt(own[label] / level[label]) for label in (POINTS, *COUNTS) if level[label]},
        typical=typical,
        kept=kept,
        correlation=correlation,
        loadings=one_factor(correlation),
    )


def _typical(samples: Sequence[PlayerWeek], profiles: Sequence[Profile]) -> dict[str, float]:
    """The typical rostered player's game, each week weighed by its games: a count's average, a percentage's
    makes over attempts, a points league's points."""
    weighed: dict[str, float] = {}
    over: dict[str, float] = {}
    for player, profile in zip(samples, profiles, strict=True):
        games = len(player.nights)
        for label, value in profile.mean.items():
            weighed[label] = weighed.get(label, 0.0) + games * value
            over[label] = over.get(label, 0.0) + games * profile.attempts.get(label, 1.0)
    return {label: weighed[label] / over[label] for label in weighed if over[label]}


def _kept(
    samples: Sequence[PlayerWeek],
    profiles: Sequence[Profile],
    actuals: Sequence[Totals],
    typical: Mapping[str, float],
    plays: float,
) -> dict[str, float]:
    """How much of each player's distance from `typical` his weeks bore out: the slope, through nought, of what
    he did beyond the typical player on what was projected beyond him — a percentage's makes beyond the typical
    rate on the shots he took."""
    across: dict[str, float] = {}
    spread: dict[str, float] = {}
    for player, profile, actual in zip(samples, profiles, actuals, strict=True):
        games = len(player.nights) * plays
        for label, value in profile.mean.items():
            usual = typical.get(label, 0.0)
            if label in profile.attempts:
                beyond = games * (value - usual * profile.attempts[label])
                did = actual.mean.get(label, 0.0) - usual * actual.attempts.get(label, 0.0)
            else:
                beyond = games * (value - usual)
                did = actual.mean.get(label, 0.0) - games * usual
            across[label] = across.get(label, 0.0) + beyond * did
            spread[label] = spread.get(label, 0.0) + beyond**2
    return {label: across[label] / spread[label] for label in across if spread[label]}


def _profile(player: PlayerWeek, spreads: Uncertainty) -> Profile:
    """A game of him as both a category league's line and a points league's fantasy points read it."""
    lines = line_profile(player.value, player.line, player.form, spreads)
    points = points_profile(player.value, player.form, RANKING_WEIGHTS, spreads)
    return Profile(
        value=player.value,
        mean={**lines.mean, **points.mean},
        variance={**lines.variance, **points.variance},
        attempts=lines.attempts,
    )


def _week_of(player: PlayerWeek, profile: Profile, spreads: Uncertainty) -> Totals:
    """His week as the app projects it: every game his club plays that week, under `spreads`."""
    return week_totals({player.key: len(player.nights)}, {player.key: profile}, spreads)


def _actual(played: Sequence[NBAGameLog]) -> Totals:
    """What games added up to: each count, a percentage's makes and attempts, and Yahoo's default points."""
    mean: dict[str, float] = {POINTS: 0.0}
    attempts: dict[str, float] = {}
    for category in CATEGORIES:
        mean[category.label] = sum(g.get(category.made) for g in played)
        if category.is_percentage:
            attempts[category.label] = sum(g.get(category.attempts) for g in played)
    mean[POINTS] = fantasy_points(_line_of(mean), RANKING_WEIGHTS) or 0.0
    return Totals(mean=mean, attempts=attempts)


def _line_of(totals: Mapping[str, float]) -> Line:
    return {label: totals[label] for label in COUNTS}


def _misses(projected: Totals, actual: Totals) -> dict[str, float]:
    """How far each figure missed: a count by its total, a percentage by the makes beyond his rate on the
    shots he took — what moves a roster's rate once its attempts are known."""
    found = {}
    for label, value in projected.mean.items():
        if label in projected.attempts:
            taken = projected.attempts[label]
            rate = value / taken if taken else 0.0
            found[label] = actual.mean.get(label, 0.0) - rate * actual.attempts.get(label, 0.0)
        else:
            found[label] = actual.mean.get(label, 0.0) - value
    return found


def _correlation(misses: Sequence[Mapping[str, float]], labels: Sequence[str]) -> dict[str, dict[str, float]]:
    """How each label's misses move with each other's, summed over players as a roster sums them."""
    power = {label: math.sqrt(sum(m.get(label, 0.0) ** 2 for m in misses)) for label in labels}
    return {
        a: {
            b: sum(m.get(a, 0.0) * m.get(b, 0.0) for m in misses) / (power[a] * power[b])
            if power[a] and power[b]
            else float(a == b)
            for b in labels
        }
        for a in labels
    }


def one_factor(correlation: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    """Each label's loading on the one swing that best explains how they move together: principal-axis
    factoring, each round's first axis found by power iteration, signed so that more of the swing is more.

    A label's loading carries its raw figure's sign — turnovers rise with the rest — which is how
    `strength.loadings` reads it before turning a category won by less.
    """
    labels = list(correlation)
    shared = dict.fromkeys(labels, 0.5)
    loads = dict.fromkeys(labels, 0.0)
    for _ in range(FACTOR_ROUNDS):
        reduced = {a: {b: shared[a] if a == b else correlation[a][b] for b in labels} for a in labels}
        axis = dict.fromkeys(labels, 1.0)
        for _ in range(FACTOR_ROUNDS):
            moved = {a: sum(reduced[a][b] * axis[b] for b in labels) for a in labels}
            norm = math.sqrt(sum(v * v for v in moved.values())) or 1.0
            axis = {a: v / norm for a, v in moved.items()}
        size = sum(axis[a] * reduced[a][b] * axis[b] for a in labels for b in labels)
        loads = {a: axis[a] * math.sqrt(max(size, 0.0)) for a in labels}
        shared = {a: min(MOST_TOGETHER**2, loads[a] ** 2) for a in labels}
    flip = -1.0 if sum(loads.values()) < 0 else 1.0
    return {a: flip * loads[a] for a in labels}


# ── the check ───────────────────────────────────────────────────────────


def check(
    season: str, model: OddsModel, weeks: Sequence[Sequence[PlayerWeek]], leagues: int = LEAGUES, seed: int = 0
) -> OddsCheck:
    """How the spreads `model` names called the categories and weeks of `leagues` leagues dealt from each week.

    Raises:
        NotFoundError: no week to check on.
    """
    if not weeks:
        raise NotFoundError(f"a week of the {season} season to check odds on")
    spreads = MODELS[model]
    together = loadings(NINE, spreads)
    categories: list[tuple[float, float]] = []
    matchups: list[tuple[float, float]] = []
    for number, pool in enumerate(weeks):
        rng = random.Random(seed * 1_000 + number)
        profiles = {p.key: line_profile(p.value, p.line, p.form, spreads) for p in pool}
        planned = {p.key: frozenset(p.nights) for p in pool}
        for _ in range(leagues):
            dealt = list(pool)
            rng.shuffle(dealt)
            rosters = [dealt[i::TEAMS] for i in range(TEAMS)]
            for home, away in zip(rosters[::2], rosters[1::2], strict=True):
                mine, theirs = (_best_first(roster) for roster in (home, away))
                projected = [week_totals(started(side, planned, SLOTS), profiles, spreads) for side in (mine, theirs)]
                chances = category_chances(projected[0], projected[1], NINE)
                results = _results(_week(home, mine), _week(away, theirs))
                categories += zip(chances, results, strict=True)
                win, loss = week_chances(chances, together)
                taken = sum(results) - len(results) / 2
                matchups.append((win + (1 - win - loss) / 2, 1.0 if taken > 0 else 0.0 if taken < 0 else 0.5))
    return OddsCheck(
        season=season,
        model=model,
        weeks=len(weeks),
        categories=calibration(categories, width=0.1),
        matchups=calibration(matchups),
    )


def _best_first(roster: Sequence[PlayerWeek]) -> list[str]:
    return [p.key for p in sorted(roster, key=lambda p: (-p.value, p.key))]


def _week(roster: Sequence[PlayerWeek], order: Sequence[str]) -> Totals:
    """What a roster's week added up to: each night, the first `SLOTS` of `order` who played."""
    games = {p.key: {_day(g): g for g in p.played} for p in roster}
    filled: dict[date, int] = {}
    counted: list[NBAGameLog] = []
    for key in order:
        for night, game in sorted(games[key].items()):
            if filled.get(night, 0) < SLOTS:
                filled[night] = filled.get(night, 0) + 1
                counted.append(game)
    return _actual(counted)


def _results(mine: Totals, theirs: Totals) -> list[float]:
    """Each of the nine categories as it went for `mine`: one taken, nought lost, a half level."""
    found = []
    for category in NINE:
        ours, other = (_figure(side, category) for side in (mine, theirs))
        if category.fewer_wins:
            ours, other = -ours, -other
        found.append(1.0 if ours > other else 0.0 if ours < other else 0.5)
    return found


def _figure(side: Totals, category: Scored) -> float:
    made = side.mean.get(category.label, 0.0)
    if not category.percentage:
        return made
    taken = side.attempts.get(category.label, 0.0)
    return round(made / taken, PERCENT_PLACES) if taken else -math.inf


# ── reading seasons ─────────────────────────────────────────────────────


class NBAOddsTuning:
    """`OddsTuning` for basketball, from Sleeper's box scores and projections: each season read once and kept."""

    def __init__(self, games: SleeperNBASource, projections: SleeperProjectionSource) -> None:
        self.games = games
        self.projections = projections
        self._weeks: dict[str, list[list[PlayerWeek]]] = {}

    def seasons(self) -> tuple[str, str]:
        state = self.games.get_nba_state()
        return str(int(state.season) - 1), state.season

    def fit_odds(self, season: str) -> OddsFit:
        return fit(season, self._season(season))

    def check_odds(self, season: str, model: OddsModel) -> OddsCheck:
        return check(season, model, self._season(season))

    def _season(self, season: str) -> list[list[PlayerWeek]]:
        """Every week of `season` as its rostered-calibre players' weeks: the whole of a season finished, the
        weeks so far of the one being played.

        Raises:
            SleeperAPIError: a week's box scores or projections would not load.
        """
        if season not in self._weeks:
            state = self.games.get_nba_state()
            weeks = list(range(1, (state.week if season == state.season else SEASON_WEEKS) + 1))
            logs = self.games.get_nba_game_logs(season, weeks)
            projected = [row for week in weeks for row in self.projections.get_nba_projections(season, week)]
            self._weeks[season] = weeks_of(logs, projected)
            logger.info(f"Read {len(self._weeks[season])} weeks of the {season} season")
        return self._weeks[season]
