"""What each NBA club gives up to each position, read from the window's box scores (`competitions/matchups.py`).

Sleeper files every player's line against the club he played, and its catalog
says each player's position: summed by opponent and position, per game that
opponent played, they say which clubs a point guard eats against. Points in a
category league, the league's fantasy points in a points one.
"""

from collections.abc import Iterator, Mapping

from thefrontoffice.adapters.outbound.competitions import matchups
from thefrontoffice.adapters.outbound.competitions.matchups import Matchup, Scored
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores
from thefrontoffice.adapters.outbound.competitions.nba.rules import POINTS, POSITIONS, fantasy_points, line

POINTS_UNIT = "pts"
FANTASY_UNIT = "fpts"


def allowed(scores: BoxScores, weights: Mapping[str, float] | None = None) -> dict[tuple[str, str], Matchup]:
    """Every club's record against every position, by (club, position), as Sleeper abbreviates and names them.

    A player Sleeper's catalog gives no position of the five counts for nobody.
    """
    return matchups.allowed(_scored(scores, weights), unit=FANTASY_UNIT if weights else POINTS_UNIT)


def _scored(scores: BoxScores, weights: Mapping[str, float] | None) -> Iterator[Scored]:
    for player_id, logs in scores.logs.items():
        meta = scores.players.get(player_id)
        if meta is None or meta.position not in POSITIONS:
            continue
        for log in logs:
            if not log.opponent:
                continue
            figure = (fantasy_points(line(log.stats), weights) or 0.0) if weights else log.get(POINTS.made)
            yield Scored(log.opponent, meta.position, log.date, figure)
