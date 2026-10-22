"""Each football player's week as a range of outcomes, for the simulation.

The range is centred on this week's projection — which already reads the
matchup — and shaped by his own games: each one, rescaled so that their
average is the projection, is one equally likely way the week could go. A
receiver who has gone 3, 4 and 31 keeps that boom-or-bust shape; one who has
gone 11, 12 and 13 stays steady.

A thin history leans on his position's: every player at it, each game
rescaled the same way. The fewer games of his own, the more it leans — so a
rookie with two games is mostly his position, a starter with seven mostly
himself.

Whether he plays at all is his injury designation, at rough rates for now.
A game already finished fixes his score at what it was; one under way adds
half a game to what he has.
"""

from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.platforms.sleeper.types import WeeklyProjection
from thefrontoffice.domain.models import Outcomes

OWN_HALF = 4
"""Games of his own at which his history counts as much as his position's."""

MIN_MEAN = 6.0
"""Below this a player's average is too small to rescale by: a backup's one good game
against his two-point average reads as a six-fold week, and lent to a star it is fiction."""

MIN_GAMES = 3
"""Games a player needs before his spread joins his position's pool."""

MAX_RATIO = 4.0
"""No single game counts for more than four times a player's average."""

POOL_SIZE = 200
"""Points of the position's spread kept: evenly spaced through it, so the shape survives."""

UNDER_WAY = 0.5
"""How much of a game is left once it has kicked off. Sleeper gives no clock, so a guess."""

# The chance a player plays, by designation. Rough base rates, and the slot a
# news reading of his situation would replace.
PLAYS = {
    "OUT": 0.0,
    "IR": 0.0,
    "PUP": 0.0,
    "SUS": 0.0,
    "NA": 0.0,
    "DNR": 0.0,
    "DOUBTFUL": 0.25,
    "QUESTIONABLE": 0.8,
}


@dataclass(frozen=True)
class Spreads:
    """Every player's games as ratios to his own average, and every position's pooled."""

    own: dict[str, tuple[float, ...]]
    pool: dict[str, tuple[float, ...]]


def spreads(evidence: Evidence) -> Spreads:
    own: dict[str, tuple[float, ...]] = {}
    pooled: dict[str, list[float]] = {}
    for player_id, games in evidence.games.items():
        mean = sum(games) / len(games)
        if mean < MIN_MEAN:
            continue
        ratios = tuple(min(points / mean, MAX_RATIO) for points in games)
        own[player_id] = ratios
        if len(games) >= MIN_GAMES:
            pooled.setdefault(evidence.positions[player_id], []).extend(ratios)
    return Spreads(own=own, pool={position: _evenly(sorted(r), POOL_SIZE) for position, r in pooled.items()})


def outcomes(
    player: WeeklyProjection,
    spread: Spreads,
    *,
    status: str = "",
    scored: float = 0.0,
) -> Outcomes:
    """His week: the range, the chance he plays, and what `status` says of his game.

    `status` is his game's — Sleeper's `pre_game`, `in_game` or `complete` —
    and `scored` what he has so far.
    """
    if status == "complete":
        return Outcomes(player.player_id, player.name, player.points, (), floor=scored, remaining=0.0)
    ratios = _blend(spread.own.get(player.player_id, ()), spread.pool.get(player.position, ()))
    samples = tuple(player.points * r for r in ratios) if ratios else (player.points,)
    started = bool(status) and status != "pre_game"
    return Outcomes(
        player_id=player.player_id,
        name=player.name,
        projection=player.points,
        samples=samples,
        # A game under way settles whether he is playing: he is, or his
        # points so far say he is not.
        plays=1.0 if started else PLAYS.get(player.injury_status.upper(), 1.0) if player.opponent else 0.0,
        floor=scored if started else 0.0,
        remaining=UNDER_WAY if started else 1.0,
    )


def _blend(own: tuple[float, ...], pool: tuple[float, ...]) -> tuple[float, ...]:
    """His ratios and his position's, mixed so his weigh `n / (n + OWN_HALF)` of the whole."""
    if not pool:
        return own
    if not own:
        return pool
    weight = len(own) / (len(own) + OWN_HALF)
    copies = max(1, round(weight * len(pool) / ((1 - weight) * len(own))))
    return own * copies + pool


def _evenly(values: list[float], count: int) -> tuple[float, ...]:
    """`count` values spaced evenly through a sorted list — its shape at a fixed size."""
    if len(values) <= count:
        return tuple(values)
    step = (len(values) - 1) / (count - 1)
    return tuple(values[round(i * step)] for i in range(count))
