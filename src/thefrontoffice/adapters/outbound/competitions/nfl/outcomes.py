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
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.domain.models import Outcomes


@dataclass(frozen=True)
class RangeSettings:
    """What shapes a range — the few numbers `just tune` searches over.

    Defaults are what the app runs with, set by `just tune`: chosen on weeks
    2-5 of the 2026 season and kept because they also won on week 6, which
    they never saw — 78% of player-games inside the 10th-90th band (70% with
    the earlier hand-set values) against the 80% a true range would hold.
    """

    own_half: float = 8
    """Games of his own at which his history counts as much as his position's."""

    min_mean: float = 6.0
    """Below this a player's average is too small to rescale by: a backup's one good game
    against his two-point average reads as a six-fold week, and lent to a star it is fiction."""

    min_games: int = 3
    """Games a player needs before his spread joins his position's pool."""

    max_ratio: float = 3.0
    """No single game counts for more than this many times a player's average."""

    projection_error: float = 0.3
    """How far the projection itself may be off, as a share of it: each simulated week
    scales his whole game by a factor around 1 with this spread. Widens a range without
    moving its centre — the honest answer to "the projection is a guess too"."""

    shared_error: float = 0.25
    """Of `projection_error`, the part a quarterback shares with his own receivers and
    tight ends: an offense that moves the ball lifts all of them at once. Measured on
    weeks 2-6 of 2026, where a quarterback's week and a pass-catcher's on the same team
    correlated at +0.20 against their projections — a shared factor of about 0.29 —
    chosen a little under that and checked on `just backtest`. Backs are left out:
    against their quarterback they move independently, and against each other they
    split the carries, which no shared factor can say."""


DEFAULT = RangeSettings()
MAX_RATIO = DEFAULT.max_ratio

POOL_SIZE = 200
"""Points of the position's spread kept: evenly spaced through it, so the shape survives."""

UNDER_WAY = 0.5
"""How much of a game is left once it has kicked off, where no scoreboard says: Sleeper gives no clock, so a guess."""

PASSING_GAME = frozenset({"QB", "WR", "TE"})
"""Positions whose weeks rise and fall with their own team's passing game."""

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


def spreads(evidence: Evidence, settings: RangeSettings = DEFAULT, pool_from: Evidence | None = None) -> Spreads:
    """Each player's own spread from `evidence`; each position's from it and `pool_from` together.

    `pool_from` is last season. A position's spread barely moves from one
    year to the next, and without it the opening weeks have no pool at all
    — nobody has the games yet — so every range collapses to its projection.
    A player's own spread stays this season's: roles change over a summer.
    """
    own = {pid: ratios for pid, (ratios, _) in _ratios(evidence, settings).items()}
    pooled: dict[str, list[float]] = {}
    for source in (evidence, pool_from):
        if source is None:
            continue
        for ratios, position in _ratios(source, settings).values():
            if len(ratios) >= settings.min_games:
                pooled.setdefault(position, []).extend(ratios)
    return Spreads(own=own, pool={position: _evenly(sorted(r), POOL_SIZE) for position, r in pooled.items()})


def _ratios(evidence: Evidence, settings: RangeSettings) -> dict[str, tuple[tuple[float, ...], str]]:
    """Each player's games as ratios to his average, capped, for those averaging enough to rescale.

    Rescaled after the cap so they still average 1: trimming a boom week
    takes points off the top, and left alone that would centre every
    streaky player's range below his projection.
    """
    found = {}
    for player_id, games in evidence.games.items():
        mean = sum(games) / len(games)
        if mean < settings.min_mean:
            continue
        capped = [min(points / mean, settings.max_ratio) for points in games]
        centre = sum(capped) / len(capped)
        found[player_id] = (tuple(r / centre for r in capped), evidence.positions[player_id])
    return found


def outcomes(
    player: Projection,
    spread: Spreads,
    *,
    status: str = "",
    scored: float = 0.0,
    left: float = UNDER_WAY,
    settings: RangeSettings = DEFAULT,
) -> Outcomes:
    """His week: the range, the chance he plays, and what `status` says of his game.

    `status` is his game's — Sleeper's `pre_game`, `in_game` or `complete` —
    `scored` what he has so far, and `left` how much of it is still to
    play — the scoreboard's clock where there is one.
    """
    if status == "complete":
        return Outcomes(player.player_id, player.name, player.points, (), floor=scored, remaining=0.0)
    ratios = _blend(spread.own.get(player.player_id, ()), spread.pool.get(player.position, ()), settings.own_half)
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
        remaining=left if started else 1.0,
        projection_error=settings.projection_error,
        group=f"{player.team}:pass" if player.position in PASSING_GAME and player.team else "",
        shared_error=settings.shared_error,
    )


def _blend(own: tuple[float, ...], pool: tuple[float, ...], own_half: float) -> tuple[float, ...]:
    """His ratios and his position's, mixed so his weigh `n / (n + own_half)` of the whole."""
    if not pool:
        return own
    if not own:
        return pool
    weight = len(own) / (len(own) + own_half)
    copies = max(1, round(weight * len(pool) / ((1 - weight) * len(own))))
    return own * copies + pool


def _evenly(values: list[float], count: int) -> tuple[float, ...]:
    """`count` values spaced evenly through a sorted list — its shape at a fixed size."""
    if len(values) <= count:
        return tuple(values)
    step = (len(values) - 1) / (count - 1)
    return tuple(values[round(i * step)] for i in range(count))
