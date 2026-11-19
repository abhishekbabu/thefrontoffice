"""The rest of the regular season played many times over: who reaches the playoffs.

Generic, like the week's forecast. A provider describes the season — each
team's record, the fixtures left, how each team is expected to score in each
week — and this plays every remaining matchup, seeds the table by record and
then points for, and counts how often each team finishes in a playoff place.

The odds are also split on this week's result, because that is the part
still in the manager's hands: "74% win / 52% loss" says what this week is
worth in a way a single figure cannot.
"""

import logging
import random
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace

from thefrontoffice.application.results import WORTH, result
from thefrontoffice.domain.models import (
    Fixture,
    PlayoffOdds,
    SeasonInput,
    TeamOdds,
    TeamWeek,
    TradeIdea,
    TradeMarket,
    TradeOption,
    TradeRank,
    Trades,
    outcome,
)
from thefrontoffice.domain.ports import SeasonProvider, TradeMarketProvider

logger = logging.getLogger(__name__)

SEASONS = 5_000
"""Enough that a playoff chance moves by about a point between seeds."""

TRADES_SHOWN = 5

TRADES_TRIED = 12
"""Trades played out against the season, the best by points first, since each costs a simulation."""

TRADES_PER_TEAM = 3
"""So one manager's roster cannot fill the whole list with variations on a deal."""

MIN_TRADE_CHANGE = 0.005
"""Half a point of playoff chance: less than that is a trade that changes nothing worth asking for."""

MIN_THEIR_GAIN = 0.5
"""Points a week their starters must gain: the least that reads as a reason for them to say yes.
A market counted in another measure, or on another scale, names its own (`TradeMarket.least_their_gain`)."""

OUT_OF_IT = 0.05
"""Their playoff chance below which a manager has no lineup left to improve, only what he gives and gets to weigh."""

SAFE = 0.8
"""Your playoff chance above which a trade is for the points it adds over the rest of the season —
the regular season's weeks for seeding and a bye, the playoff weeks the table's simulation never
reaches — since from there a few points of chance are worth less than a better lineup."""

MIN_TOTAL_GAIN = 3.0
"""Expected points over the rest of the season: less than about a point a playoff week is a trade
not worth the asking. A market on another scale names its own (`TradeMarket.least_total_gain`)."""

SHARED_FROM = 2
"""Trades naming the same pickup from which he is said once under the list rather than on each."""


def simulate_season(season: SeasonInput, simulations: int = SEASONS) -> PlayoffOdds:
    """Play out the rest of the regular season `simulations` times."""
    rng = random.Random(season.seed)
    scoring = {(t.team_id, t.week): (t.mean, t.spread) for t in season.scoring}
    ids = [t.team_id for t in season.teams]
    made = dict.fromkeys(ids, 0)
    # Your playoff finishes, split by how this week went for you.
    split = {"win": [0, 0], "loss": [0, 0]}
    gauss = rng.gauss

    for _ in range(simulations):
        wins = {t.team_id: t.wins + WORTH["drawn"] * t.ties for t in season.teams}
        points = {t.team_id: t.points_for for t in season.teams}
        offset = {team: gauss(0.0, season.strength_error) if season.strength_error else 0.0 for team in ids}
        this_week = ""
        for fixture in season.fixtures:
            if fixture.chances is None:
                home, away = (
                    _score(scoring, team, fixture.week, gauss, offset[team]) for team in (fixture.home, fixture.away)
                )
                points[fixture.home] += home
                points[fixture.away] += away
            else:
                # Won on categories: no score to add to points for, only who took the week.
                home, away = _drawn(fixture.chances, rng.random())
            for team, share in ((fixture.home, result(home, away)), (fixture.away, result(away, home))):
                wins[team] += share
            if fixture.week == season.week and season.mine in (fixture.home, fixture.away):
                mine = home if fixture.home == season.mine else away
                theirs = away if fixture.home == season.mine else home
                # A tie is not the win the split is asking about.
                this_week = "win" if outcome(mine, theirs) == "won" else "loss"
        seeded = sorted(ids, key=lambda team: (-wins[team], -points[team]))[: season.spots]
        for team in seeded:
            made[team] += 1
        if this_week:
            split[this_week][0] += season.mine in seeded
            split[this_week][1] += 1

    def chance(week_was: str) -> float | None:
        reached, played = split[week_was]
        return reached / played if played else None

    return PlayoffOdds(
        spots=season.spots,
        teams=sorted(
            (TeamOdds(team_id=t.team_id, name=t.name, playoffs=made[t.team_id] / simulations) for t in season.teams),
            key=lambda odds: -odds.playoffs,
        ),
        playoffs=made.get(season.mine, 0) / simulations,
        with_win=chance("win"),
        with_loss=chance("loss"),
        simulations=simulations,
    )


def _score(
    scoring: dict[tuple[str, int], tuple[float, float]],
    team: str,
    week: int,
    gauss: Callable[[float, float], float],
    offset: float,
) -> float:
    """One team's score in one simulated week: around its mean and this season's offset, never below nought."""
    mean, spread = scoring.get((team, week), (0.0, 0.0))
    return max(0.0, gauss(mean + offset, spread) if spread else mean + offset)


def _drawn(chances: tuple[float, float], draw: float) -> tuple[float, float]:
    """A week decided on chances, as the two scores a result reads: one to nought either way, or level."""
    home_wins, away_wins = chances
    if draw < home_wins:
        return 1.0, 0.0
    if draw < home_wins + away_wins:
        return 0.0, 1.0
    return 0.0, 0.0


# ── this week, weighed in ───────────────────────────────────────────────────────


def chance_now(odds: PlayoffOdds, win: float | None) -> float:
    """Your playoff chance, with this week weighed by the week's own forecast where there is one.

    The season simulation scores this week from each team's average; the
    week's forecast knows the actual lineups and who is questionable, so
    where it exists it decides how likely the win and the loss are.
    """
    if win is None or odds.with_win is None or odds.with_loss is None:
        return odds.playoffs
    return win * odds.with_win + (1 - win) * odds.with_loss


class SeasonEngine:
    """A provider's regular season, simulated to its end."""

    def __init__(self, provider: SeasonProvider):
        self.provider = provider

    def odds(self, league_id: str) -> PlayoffOdds | None:
        """Every team's playoff chance; None where the season is over or there are no playoffs to reach."""
        season = self.provider.season_input(league_id)
        if season is None or not season.spots:
            return None
        logger.info(f"Simulating {len(season.fixtures)} fixtures to the playoffs")
        return simulate_season(season)


class MarketEngine:
    """The trades worth offering, priced against the playoff race and the playoffs after it."""

    def __init__(self, provider: TradeMarketProvider):
        self.provider = provider

    def trades(self, league_id: str) -> Trades:
        """The trades that would do most for you, best first; none past the deadline.

        A manager will take a trade near even in worth if it helps his
        starters, or if he has no playoff place left to chase. Which do most
        for you depends on where you stand: a team on the bubble needs its
        playoff chance, and a team already safe needs points — in the regular
        season left, for its seed, and in the playoff weeks, which the season's
        simulation never plays.

        Every trade is played out over the same seasons as the league without
        it — one seed, the same draws in the same order — so the difference is
        the trade and not the luck of two different sets of seasons.
        """
        market = self.provider.trade_market(league_id)
        if market is None or not market.season.spots or not market.options:
            return Trades()
        before = simulate_season(market.season)
        chances = {t.team_id: t.playoffs for t in before.teams}
        safe = before.playoffs >= SAFE

        def for_you(option: TradeOption) -> float:
            if safe:
                return _total(market, option.points, option.playoff_points, before.playoffs)
            return option.points

        their_least = MIN_THEIR_GAIN if market.least_their_gain is None else market.least_their_gain
        acceptable = [
            option
            for option in market.options
            if option.their_points >= their_least or chances.get(option.team_id, 0.0) < OUT_OF_IT
        ]
        tried = sorted(_per_team(acceptable, for_you), key=lambda option: -for_you(option))[:TRADES_TRIED]
        logger.info(f"Pricing {len(tried)} of {len(market.options)} trades against the playoff race")
        names = {t.team_id: t.name for t in market.season.teams}
        ideas = [_priced(market, before, option, names) for option in tried]
        total_least = MIN_TOTAL_GAIN if market.least_total_gain is None else market.least_total_gain
        worth = [idea for idea in ideas if _worth_offering(idea, total_least)]
        if safe:
            shown = sorted(worth, key=lambda idea: (-idea.total, -idea.playoffs_change))
        else:
            shown = sorted(worth, key=lambda idea: (-idea.playoffs_change, -idea.points))
        ranked_by: TradeRank = "total" if safe else "playoffs_change"
        return _said_once(shown[:TRADES_SHOWN]).model_copy(
            update={"ranked_by": ranked_by, "measure": market.measure, "deadline": market.deadline}
        )


def _total(market: TradeMarket, points: float, playoff_points: float | None, chance: float) -> float:
    """Points a week over the season left, summed: each regular-season week, and each playoff week
    weighed by the chance of playing in it.

    The playoff weeks count at the playoff chance alone, not shrinking round
    by round: a later round is less likely to be reached, but it is the one
    the title is decided in, and the two are taken to cancel.
    """
    return points * market.regular_weeks + chance * (playoff_points or 0.0) * market.playoff_weeks


def _said_once(ideas: list[TradeIdea]) -> Trades:
    """The list with nothing said twice: a pickup most trades share hoisted out of them, and each
    player's form said on the first trade he is in.

    Five trades freeing a spot for the same free agent are one fact about the
    wire, not five about the trades.
    """
    named = Counter(idea.pickup for idea in ideas if idea.pickup)
    shared = next((pickup for pickup, count in named.most_common(1) if count >= SHARED_FROM), "")
    said: set[str] = set()
    kept: list[TradeIdea] = []
    for idea in ideas:
        form = [line for line in idea.form if line.label not in said]
        said.update(line.label for line in form)
        pickup = "" if idea.pickup == shared else idea.pickup
        kept.append(idea.model_copy(update={"pickup": pickup, "form": form}))
    return Trades(ideas=kept, pickup=shared)


def _per_team(options: list[TradeOption], key: Callable[[TradeOption], float]) -> list[TradeOption]:
    """The best few with each team, and only the best way to get each of their players.

    Two offers for the same player that differ only in who goes with him are
    one idea, and the second crowds out a different one.
    """
    best: dict[tuple[str, tuple[str, ...]], TradeOption] = {}
    for option in sorted(options, key=lambda o: -key(o)):
        best.setdefault((option.team_id, option.receiving), option)
    kept: list[TradeOption] = []
    for team in dict.fromkeys(option.team_id for option in best.values()):
        kept += [o for o in best.values() if o.team_id == team][:TRADES_PER_TEAM]
    return kept


def _worth_offering(idea: TradeIdea, total_least: float) -> bool:
    """It raises your playoff chance, or your points over the rest of the season by `total_least` without
    costing you that chance — and never a trade that loses you points both before the playoffs and in them."""
    if idea.points < 0 and idea.playoff_points is not None and idea.playoff_points < 0:
        return False
    if idea.playoffs_change >= MIN_TRADE_CHANGE:
        return True
    return idea.total >= total_least and idea.playoffs_change > -MIN_TRADE_CHANGE


def _priced(market: TradeMarket, before: PlayoffOdds, option: TradeOption, names: dict[str, str]) -> TradeIdea:
    season = market.season
    after = simulate_season(
        replace(
            season,
            scoring=_with_rows(season.scoring, option.scoring),
            fixtures=_with_fixtures(season.fixtures, option.fixtures),
        )
    )

    def chance(odds: PlayoffOdds) -> float:
        return next((t.playoffs for t in odds.teams if t.team_id == option.team_id), 0.0)

    return TradeIdea(
        team_id=option.team_id,
        team=names.get(option.team_id, option.team_id),
        giving=list(option.giving),
        receiving=list(option.receiving),
        giving_ids=list(option.giving_ids),
        receiving_ids=list(option.receiving_ids),
        playoffs=after.playoffs,
        playoffs_change=after.playoffs - before.playoffs,
        their_playoffs_change=chance(after) - chance(before),
        points=option.points,
        their_points=option.their_points,
        playoff_points=option.playoff_points,
        total=_total(market, option.points, option.playoff_points, after.playoffs),
        their_playoffs=chance(before),
        pickup=option.pickup,
        form=list(option.form),
    )


def _with_fixtures(fixtures: tuple[Fixture, ...], rows: Iterable[Fixture]) -> tuple[Fixture, ...]:
    """The season's fixtures with some replaced: the same matchups, their chances after a trade."""
    replaced = {(row.week, row.home, row.away): row for row in rows}
    return tuple(replaced.get((row.week, row.home, row.away), row) for row in fixtures)


def _with_rows(scoring: tuple[TeamWeek, ...], rows: Iterable[TeamWeek]) -> tuple[TeamWeek, ...]:
    """The season's scoring with some team-weeks replaced."""
    replaced = {(row.team_id, row.week): row for row in rows}
    return tuple(replaced.get((row.team_id, row.week), row) for row in scoring)
