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
from collections.abc import Callable

from thefrontoffice.domain.models import (
    LeagueSchedule,
    PlayoffOdds,
    SeasonInput,
    Stat,
    Summary,
    TeamOdds,
)
from thefrontoffice.domain.ports import SeasonProvider

logger = logging.getLogger(__name__)

SEASONS = 5_000
"""Enough that a playoff chance moves by about a point between seeds."""


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
        wins = {t.team_id: t.wins + 0.5 * t.ties for t in season.teams}
        points = {t.team_id: t.points_for for t in season.teams}
        offset = {team: gauss(0.0, season.strength_error) if season.strength_error else 0.0 for team in ids}
        this_week = ""
        for fixture in season.fixtures:
            home, away = (
                _score(scoring, team, fixture.week, gauss, offset[team]) for team in (fixture.home, fixture.away)
            )
            points[fixture.home] += home
            points[fixture.away] += away
            for team, share in ((fixture.home, _share(home, away)), (fixture.away, _share(away, home))):
                wins[team] += share
            if fixture.week == season.week and season.mine in (fixture.home, fixture.away):
                mine = home if fixture.home == season.mine else away
                theirs = away if fixture.home == season.mine else home
                # A tie is not the win the split is asking about.
                this_week = "win" if mine > theirs else "loss"
        seeded = sorted(ids, key=lambda team: (-wins[team], -points[team]))[: season.spots]
        for team in seeded:
            made[team] += 1
        if this_week:
            split[this_week][0] += season.mine in seeded
            split[this_week][1] += 1

    def chance(outcome: str) -> float | None:
        reached, played = split[outcome]
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


def _share(mine: float, theirs: float) -> float:
    """What a result adds to a record: a win, half for a tie, nothing for a loss."""
    return 1.0 if mine > theirs else 0.5 if mine == theirs else 0.0


# ── onto the page ───────────────────────────────────────────────────────


def chance_now(odds: PlayoffOdds, win: float | None) -> float:
    """Your playoff chance, with this week weighed by the week's own forecast where there is one.

    The season simulation scores this week from each team's average; the
    week's forecast knows the actual lineups and who is questionable, so
    where it exists it decides how likely the win and the loss are.
    """
    if win is None or odds.with_win is None or odds.with_loss is None:
        return odds.playoffs
    return win * odds.with_win + (1 - win) * odds.with_loss


def attach_season(summary: Summary, odds: PlayoffOdds) -> Summary:
    """The week's header with the playoff chance, and what this week is worth to it."""
    chance = chance_now(odds, summary.forecast.win if summary.forecast else None)
    tone = "good" if chance >= 0.75 else "warning" if chance <= 0.25 else "neutral"
    stake = (
        f" · {odds.with_win:.0%} with a win, {odds.with_loss:.0%} without"
        if odds.with_win is not None and odds.with_loss is not None
        else ""
    )
    stat = Stat(label="Playoffs", value=f"{chance:.0%}{stake}", tone=tone)
    return summary.model_copy(update={"headline": [*summary.headline, stat]})


def attach_table(schedule: LeagueSchedule, odds: PlayoffOdds) -> LeagueSchedule:
    """The league table with each team's playoff chance on its row."""
    by_team = {t.team_id: t.playoffs for t in odds.teams}
    rows = [
        row.model_copy(update={"playoffs": f"{by_team[row.team_id]:.0%}"}) if row.team_id in by_team else row
        for row in schedule.standings
    ]
    return schedule.model_copy(update={"standings": rows})


class SeasonEngine:
    """A provider's regular season, simulated to its end."""

    def __init__(self, provider: SeasonProvider):
        self.provider = provider

    def odds(self, league_id: str) -> PlayoffOdds | None:
        """Every team's playoff chance; None where the season is over or there are no playoffs to reach."""
        season = self.provider.season_input(league_id)
        if season is None or not season.spots:
            return None
        logger.info(f"{self.provider.label}: simulating {len(season.fixtures)} fixtures to the playoffs")
        return simulate_season(season)
