"""The chance a club keeps a clean sheet in one match: its defence against the attack it faces, home or away.

FPL rates every fixture 1-5 but publishes no clean-sheet odds, and its rating
is a club's reputation more than its season: a leaky side and a tight one get
the same 3 against the same mid-table attack. The season's own numbers say
more, and the game already serves them — every match's score, and each
player's expected goals and goals conceded. So a match is the classic Poisson
reading of football:

    goals against = league average × opponent's attack × his club's defence × the opponent's venue
    clean sheet   = exp(−goals against)

A club's attack is its expected goals a match (its players' xG summed) over the
league's, and its defence its expected goals conceded (its keepers' xGC summed,
one keeper being on the pitch at a time) over the same — real goals where the
catalog carries no expected ones. Each is settled toward the league's average
by `PRIOR_MATCHES` of it, so three games into a season a club is mostly
average and by Christmas mostly itself. The venue is the league's split of
goals between home and away sides, settled toward even (`VENUE_PRIOR_MATCHES`).

Where a club has played nothing yet, there is nothing to read, and the fixture's
difficulty stands in (`DIFFICULTY_ODDS`).
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Opponent, Player

PRIOR_MATCHES = 6
"""Matches of the league average a club's own rate is settled with.

About the point an attack or a defence stops being a few lucky or unlucky
afternoons: after six of its own it is half itself, after twelve two-thirds.
"""

VENUE_PRIOR_MATCHES = 40
"""Matches of an even split the league's home advantage is settled with: four gameweeks of it."""

DIFFICULTY_ODDS = {1: 0.5, 2: 0.4, 3: 0.3, 4: 0.2, 5: 0.12}
"""The chance of a clean sheet by the fixture's difficulty, for a club with no season to read.

About half of matches against the weakest attacks end goalless for the
defending side, and about one in eight against the strongest.
"""

AVERAGE_DIFFICULTY = 3


@dataclass(frozen=True)
class Strength:
    """Every club's attack and defence beside the league's, and what playing at home is worth."""

    average: float = 0.0
    """Goals (expected, where the catalog has them) a side scores in a match, across the league; nought with none."""

    attack: Mapping[str, float] = field(default_factory=dict)
    """Each club's goals a match over `average`, settled toward 1."""

    defence: Mapping[str, float] = field(default_factory=dict)
    """Each club's goals conceded a match over `average`, settled toward 1: above 1 is a leaky side."""

    home: float = 1.0
    """What a home side's goals are multiplied by; an away side's by 2 − this."""

    def conceded(self, club: str, opponent: Opponent) -> float | None:
        """The goals `club` should concede against `opponent`; None where either has played nothing."""
        if club not in self.defence or opponent.club not in self.attack:
            return None
        # `opponent.home` says whether `club` is at home, so the attack it faces is the other way round.
        venue = 2 - self.home if opponent.home else self.home
        return self.average * self.attack[opponent.club] * self.defence[club] * venue

    def clean_sheet(self, club: str, opponent: Opponent) -> float:
        """The chance `club` keeps a clean sheet against `opponent`: Poisson on `conceded`, else by difficulty."""
        expected = self.conceded(club, opponent)
        if expected is None:
            return DIFFICULTY_ODDS.get(opponent.difficulty or AVERAGE_DIFFICULTY, DIFFICULTY_ODDS[AVERAGE_DIFFICULTY])
        return math.exp(-expected)


def strength(catalog: Mapping[int, Player], fixtures: Iterable[Fixture]) -> Strength:
    """Every club's `Strength` from the season so far: the matches kicked off, and the catalog's expected goals."""
    played = [f for f in fixtures if f.started or f.finished]
    if not played:
        return Strength()
    matches = Counter(club for f in played for club in (f.home, f.away))
    home_goals = sum(f.home_score for f in played)
    away_goals = sum(f.away_score for f in played)
    scored, conceded = _expected(catalog)
    if not sum(scored.values()):
        scored, conceded = _goals(played)
    average = sum(scored.values()) / (2 * len(played))
    if average <= 0:
        return Strength()

    def rate(totals: Mapping[str, float], club: str) -> float:
        n = matches[club]
        return (totals.get(club, 0.0) / average + PRIOR_MATCHES) / (n + PRIOR_MATCHES)

    split = 2 * home_goals / (home_goals + away_goals) if home_goals + away_goals else 1.0
    return Strength(
        average=average,
        attack={club: rate(scored, club) for club in matches},
        defence={club: rate(conceded, club) for club in matches},
        home=(len(played) * split + VENUE_PRIOR_MATCHES) / (len(played) + VENUE_PRIOR_MATCHES),
    )


def _expected(catalog: Mapping[int, Player]) -> tuple[dict[str, float], dict[str, float]]:
    """Each club's expected goals for, its players' summed, and against, its keepers' summed."""
    scored: defaultdict[str, float] = defaultdict(float)
    conceded: defaultdict[str, float] = defaultdict(float)
    for player in catalog.values():
        scored[player.team] += player.expected_goals
        if player.position == "GKP":
            conceded[player.team] += player.expected_goals_conceded
    return dict(scored), dict(conceded)


def _goals(played: Iterable[Fixture]) -> tuple[dict[str, float], dict[str, float]]:
    """Each club's real goals for and against, where the catalog carries no expected ones."""
    scored: defaultdict[str, float] = defaultdict(float)
    conceded: defaultdict[str, float] = defaultdict(float)
    for f in played:
        scored[f.home] += f.home_score
        scored[f.away] += f.away_score
        conceded[f.home] += f.away_score
        conceded[f.away] += f.home_score
    return dict(scored), dict(conceded)
