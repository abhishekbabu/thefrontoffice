"""The rest of the regular season played many times over: who reaches the playoffs.

Generic, like the week's forecast. A provider describes the season — each
team's record, the fixtures left, how each team is expected to score in each
week — and this plays every remaining matchup, seeds the table by record and
then points for, and counts how often each team finishes in a playoff place.

The odds are also split on this week's result, because that is the part
still in the manager's hands: "61%, 74% with a win" says what this week is
worth in a way a single figure cannot.
"""

import logging
import random
from collections.abc import Callable, Iterable
from dataclasses import replace

from thefrontoffice.application.results import WORTH, result
from thefrontoffice.domain.models import (
    PlayoffOdds,
    SeasonInput,
    TeamOdds,
    TeamWeek,
    TradeIdea,
    TradeOption,
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
"""Points a week their starters must gain: the least that reads as a reason for them to say yes."""

OUT_OF_IT = 0.05
"""Their playoff chance below which a manager has no lineup left to improve, only what he gives and gets to weigh."""

SAFE = 0.8
"""Your playoff chance above which a trade is for the playoffs themselves, which the table's
simulation never reaches: from there a few points of chance are worth less than a better lineup in December."""

MIN_PLAYOFF_GAIN = 1.0
"""Projected points a playoff week: less than that is a trade not worth the asking."""


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
            home, away = (
                _score(scoring, team, fixture.week, gauss, offset[team]) for team in (fixture.home, fixture.away)
            )
            points[fixture.home] += home
            points[fixture.away] += away
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

    def trades(self, league_id: str) -> list[TradeIdea]:
        """The trades that would do most for you, best first; none past the deadline.

        A manager will take a trade near even in worth if it helps his
        starters, or if he has no playoff place left to chase. Which do most
        for you depends on where you stand: a team on the bubble needs its
        playoff chance, and a team already safe needs its lineup in the
        playoff weeks, which the season's simulation never plays.

        Every trade is played out over the same seasons as the league without
        it — one seed, the same draws in the same order — so the difference is
        the trade and not the luck of two different sets of seasons.
        """
        market = self.provider.trade_market(league_id)
        if market is None or not market.season.spots or not market.options:
            return []
        before = simulate_season(market.season)
        chances = {t.team_id: t.playoffs for t in before.teams}
        safe = before.playoffs >= SAFE

        def for_you(option: TradeOption | TradeIdea) -> float:
            if safe and option.playoff_points is not None:
                return option.playoff_points
            return option.points

        acceptable = [
            option
            for option in market.options
            if option.their_points >= MIN_THEIR_GAIN or chances.get(option.team_id, 0.0) < OUT_OF_IT
        ]
        tried = sorted(_per_team(acceptable, for_you), key=lambda option: -for_you(option))[:TRADES_TRIED]
        logger.info(f"Pricing {len(tried)} of {len(market.options)} trades against the playoff race")
        names = {t.team_id: t.name for t in market.season.teams}
        ideas = [_priced(market.season, before, option, names) for option in tried]
        worth = [idea for idea in ideas if _worth_offering(idea)]
        if safe:
            return sorted(worth, key=lambda idea: (-for_you(idea), -idea.playoffs_change))[:TRADES_SHOWN]
        return sorted(worth, key=lambda idea: (-idea.playoffs_change, -for_you(idea)))[:TRADES_SHOWN]


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


def _worth_offering(idea: TradeIdea) -> bool:
    """It raises your playoff chance, or it makes your playoff lineup better without costing you that chance."""
    if idea.playoffs_change >= MIN_TRADE_CHANGE:
        return True
    return (idea.playoff_points or 0.0) >= MIN_PLAYOFF_GAIN and idea.playoffs_change > -MIN_TRADE_CHANGE


def _priced(season: SeasonInput, before: PlayoffOdds, option: TradeOption, names: dict[str, str]) -> TradeIdea:
    after = simulate_season(replace(season, scoring=_with_rows(season.scoring, option.scoring)))

    def chance(odds: PlayoffOdds) -> float:
        return next((t.playoffs for t in odds.teams if t.team_id == option.team_id), 0.0)

    return TradeIdea(
        team_id=option.team_id,
        team=names.get(option.team_id, option.team_id),
        giving=list(option.giving),
        receiving=list(option.receiving),
        playoffs=after.playoffs,
        playoffs_change=after.playoffs - before.playoffs,
        their_playoffs_change=chance(after) - chance(before),
        points=option.points,
        their_points=option.their_points,
        playoff_points=option.playoff_points,
        their_playoffs=chance(before),
        pickup=option.pickup,
    )


def _with_rows(scoring: tuple[TeamWeek, ...], rows: Iterable[TeamWeek]) -> tuple[TeamWeek, ...]:
    """The season's scoring with some team-weeks replaced."""
    replaced = {(row.team_id, row.week): row for row in rows}
    return tuple(replaced.get((row.team_id, row.week), row) for row in scoring)
