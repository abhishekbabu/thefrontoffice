"""The week played many times over: win probability, and what each move does to it.

Generic on purpose. A provider describes its matchup — each player's range of
outcomes, whether he plays, what is already on the board, which lineup moves
to price — and this plays it out, sums each side, and counts the wins. The
engine never learns which sport it is simulating.

Every player is drawn once per simulated week, and a move reuses those same
draws: the players it does not touch roll identical dice with and without it.
So the difference between two lineups is the decision, not two different
lots of random noise — which is what makes a "+2.8% to win" worth reading.
"""

import logging
import random
from collections.abc import Sequence

from thefrontoffice.domain.models import (
    Action,
    Calibration,
    CalibrationBucket,
    Forecast,
    LineupMove,
    MarginRange,
    MatchupInput,
    Outcomes,
    PickupChance,
    PlayedMatchup,
    RangeScore,
    Urgency,
)
from thefrontoffice.domain.ports import ForecastProvider

logger = logging.getLogger(__name__)

SIMULATIONS = 10_000
"""Enough that a win chance moves by well under a point between seeds."""

WORTH_A_ROW = 0.01
"""A move the to-do list lacks earns its own row once it adds a point of win chance."""

URGENCY_ORDER: dict[Urgency, int] = {"now": 0, "soon": 1, "later": 2}


def simulate(matchup: MatchupInput, simulations: int = SIMULATIONS) -> Forecast:
    """Play the matchup `simulations` times, with and without each move."""
    rng = random.Random(matchup.seed)
    everyone = (*matchup.mine, *matchup.theirs, *(o for m in matchup.moves for o in m.into))
    shared = _shared(everyone, matchup.seed, simulations)
    draws: dict[str, list[float]] = {}
    # Both lineups first, then the movers: adding a move to price never
    # changes the dice anybody already in the matchup rolls.
    for outcomes in everyone:
        if outcomes.player_id not in draws:
            draws[outcomes.player_id] = _draw(outcomes, rng, simulations, shared.get(outcomes.group))

    mine = _totals(matchup.mine, draws, simulations)
    theirs = _totals(matchup.theirs, draws, simulations)
    margins = [m - t for m, t in zip(mine, theirs, strict=True)]
    win = _win_rate(margins)

    moves = {move.key: _win_rate(_with(move, mine, theirs, draws)) for move in matchup.moves}
    best = max(moves, key=lambda key: moves[key], default="")
    return Forecast(
        win=win,
        margin=_range(margins),
        simulations=simulations,
        moves=moves,
        best_move=best if best and moves[best] > win else "",
    )


def _shared(everyone: Sequence[Outcomes], seed: int, simulations: int) -> dict[str, list[float]]:
    """One factor per group per simulated week: the part of a week a quarterback and his receivers share.

    Each group rolls its own dice, seeded by its name, so a move that brings
    a new group in leaves every other group's weeks exactly as they were.
    """
    errors = {o.group: o.shared_error for o in everyone if o.group and o.shared_error}
    factors = {}
    for group, error in errors.items():
        rng = random.Random(f"{seed}:{group}")
        factors[group] = [max(0.0, rng.gauss(1.0, error)) for _ in range(simulations)]
    return factors


def _draw(outcomes: Outcomes, rng: random.Random, simulations: int, shared: list[float] | None = None) -> list[float]:
    """His score in each simulated week: what is on the board, plus the rest of a game if he plays.

    `shared` is his group's factor for each week. Without it — a player
    ranged on his own, as tuning does — he rolls his share himself, so his
    range is the same whether or not his teammates are in the matchup.
    """
    # Hoisted out of the loop, which runs ten thousand times a player and a
    # page of free agents is fifty players. The dice are rolled in the same
    # order as ever, so every seed gives the answer it always gave.
    random_, choice, gauss = rng.random, rng.choice, rng.gauss
    plays, samples = outcomes.plays, outcomes.samples
    common = min(outcomes.shared_error, outcomes.projection_error) if outcomes.group else 0.0
    # His own part of the projection's error, with the shared part taken out
    # of it: variances add, so the two together are as wide as the whole was.
    error = (outcomes.projection_error**2 - common**2) ** 0.5
    floor, remaining = outcomes.floor, outcomes.remaining
    draws = []
    for i in range(simulations):
        played = random_() < plays
        game = choice(samples) if samples else 0.0
        if error:
            # The projection may be off too: one factor for his whole game,
            # around 1 so the centre holds, never below 0 so a miss is not a sign flip.
            game *= max(0.0, gauss(1.0, error))
        if common:
            game *= shared[i] if shared is not None else max(0.0, gauss(1.0, common))
        draws.append(floor + (remaining * game if played else 0.0))
    return draws


def _totals(lineup: Sequence[Outcomes], draws: dict[str, list[float]], simulations: int) -> list[float]:
    totals = [0.0] * simulations
    for outcomes in lineup:
        for i, points in enumerate(draws[outcomes.player_id]):
            totals[i] += points
    return totals


def _with(move: LineupMove, mine: list[float], theirs: list[float], draws: dict[str, list[float]]) -> list[float]:
    """The margins with `move` made: the same weeks, his draws swapped for theirs."""
    margins = [m - t for m, t in zip(mine, theirs, strict=True)]
    for pid in move.out:
        if pid in draws:
            margins = [m - d for m, d in zip(margins, draws[pid], strict=True)]
    for o in move.into:
        margins = [m + d for m, d in zip(margins, draws[o.player_id], strict=True)]
    return margins


def _win_rate(margins: list[float]) -> float:
    wins = sum(1.0 if m > 0 else 0.5 if m == 0 else 0.0 for m in margins)
    return wins / len(margins) if margins else 0.5


def _range(margins: list[float]) -> MarginRange:
    ordered = sorted(margins)

    def at(share: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1) if ordered else 0.0

    return MarginRange(low=at(0.1), median=at(0.5), high=at(0.9))


# ── the to-do list, by the chance of winning ────────────────────────────


def ranked(actions: list[Action] | None, forecast: Forecast, matchup: MatchupInput) -> list[Action] | None:
    """The to-do list with what each move does to the chance of winning, ordered by it within each urgency.

    A move the list does not hold but the simulation rates — usually a
    riskier start when you are behind — becomes a row of its own. A
    competition with no list still has none.
    """
    if actions is None:
        return None
    by_move = {_identity(m): m for m in matchup.moves}
    priced = []
    for action in actions:
        move = by_move.get((action.player_id, action.replaces))
        change = forecast.moves[move.key] - forecast.win if move and move.key in forecast.moves else None
        priced.append(action.model_copy(update={"win_change": change}) if change is not None else action)

    best = next((m for m in matchup.moves if m.key == forecast.best_move), None)
    listed = {(a.player_id, a.replaces) for a in priced}
    if best is not None and forecast.moves[best.key] - forecast.win >= WORTH_A_ROW and _identity(best) not in listed:
        priced.append(_odds_row(best, forecast))

    return sorted(
        priced,
        key=lambda a: (URGENCY_ORDER[a.urgency], -(a.win_change if a.win_change is not None else float("-inf"))),
    )


def _identity(move: LineupMove) -> tuple[str, str]:
    """What a single move does — who comes in, who goes out — as a to-do item names it."""
    return (move.into[0].player_id if move.into else "", move.out[0] if move.out else "")


def _odds_row(move: LineupMove, forecast: Forecast) -> Action:
    gain = forecast.moves[move.key] - forecast.win
    return Action(
        kind="lineup",
        urgency="soon",
        key=f"odds:{move.key}",
        title=move.title,
        reason=(
            f"The best single change for your chance of winning: +{gain:.1%}. The projections would not make "
            "it — the spread of his outcomes is what suits where this matchup stands."
        ),
        player_id=move.into[0].player_id if move.into else "",
        replaces=move.out[0] if move.out else "",
        win_change=gain,
    )


def pickup_chances(forecast: Forecast, matchup: MatchupInput) -> list[PickupChance]:
    """Each player brought in by a move, at the move that does the most for the chance of winning."""
    best: dict[str, tuple[float, str]] = {}
    for move in matchup.moves:
        if not move.into or move.key not in forecast.moves:
            continue
        player_id, change = move.into[0].player_id, forecast.moves[move.key] - forecast.win
        if player_id not in best or change > best[player_id][0]:
            best[player_id] = (change, move.title)
    return [PickupChance(player_id=pid, win_change=change, title=title) for pid, (change, title) in best.items()]


# ── how well it predicts ────────────────────────────────────────────────


def calibrate(played: list[PlayedMatchup], simulations: int = SIMULATIONS) -> Calibration:
    """Score the simulation on matchups already played: its chances against what happened."""
    pairs = []
    for game in played:
        chance = simulate(game.matchup, simulations).win
        outcome = 1.0 if game.mine > game.theirs else 0.5 if game.mine == game.theirs else 0.0
        pairs.append((chance, outcome))
    if not pairs:
        return Calibration(matchups=0, brier=0.0)

    buckets = []
    for low in (0.0, 0.2, 0.4, 0.6, 0.8):
        high = low + 0.2
        inside = [(c, o) for c, o in pairs if low <= c < high or (high >= 1.0 and c == 1.0)]
        if inside:
            buckets.append(
                CalibrationBucket(
                    low=low,
                    high=high,
                    matchups=len(inside),
                    predicted=sum(c for c, _ in inside) / len(inside),
                    won=sum(o for _, o in inside) / len(inside),
                )
            )
    return Calibration(
        matchups=len(pairs),
        brier=sum((c - o) ** 2 for c, o in pairs) / len(pairs),
        buckets=buckets,
    )


DECILES = tuple(i / 10 for i in range(1, 10))


def score_ranges(played: list[tuple[Outcomes, float]], draws: int = 400, seed: int = 0) -> RangeScore:
    """How well each range held what its player then scored.

    Quantile loss is a proper score — no range scores better by being wider
    or narrower than the truth — so it is what settings are chosen on. The
    shares inside and outside the 10th–90th band say which way a range is wrong.
    """
    rng = random.Random(seed)
    inside = below = above = 0
    loss = 0.0
    for outcomes, actual in played:
        ordered = sorted(_draw(outcomes, rng, draws))
        quantiles = [ordered[min(draws - 1, int(q * draws))] for q in DECILES]
        low, high = quantiles[0], quantiles[-1]
        below += actual < low
        above += actual > high
        inside += low <= actual <= high
        loss += sum(
            (actual - q) * tau if actual >= q else (q - actual) * (1 - tau)
            for tau, q in zip(DECILES, quantiles, strict=True)
        ) / len(DECILES)
    count = len(played)
    if not count:
        return RangeScore(players=0, inside=0.0, below=0.0, above=0.0, loss=0.0)
    return RangeScore(players=count, inside=inside / count, below=below / count, above=above / count, loss=loss / count)


class ForecastEngine:
    """A provider's matchup, simulated."""

    def __init__(self, provider: ForecastProvider):
        self.provider = provider

    def forecast(self, league_id: str) -> tuple[Forecast, MatchupInput] | None:
        """This week's forecast and the matchup it came from; None where there is no opponent."""
        matchup = self.provider.matchup_input(league_id)
        if matchup is None:
            return None
        return simulate(matchup), matchup

    def pickups(self, league_id: str, player_ids: list[str]) -> list[PickupChance]:
        """What each of these free agents would do to this week's chance, started at his best.

        Empty where there is no opponent to play, or none of them could start.
        """
        if not player_ids:
            return []
        matchup = self.provider.matchup_input(league_id, candidates=player_ids)
        if matchup is None or not matchup.moves:
            return []
        return pickup_chances(simulate(matchup), matchup)

    def backtest(self, league_id: str, weeks: list[int], simulations: int = SIMULATIONS) -> Calibration:
        played = [game for week in weeks for game in self.provider.played_matchups(league_id, week)]
        logger.info(f"{self.provider.label}: backtesting {len(played)} matchups over weeks {weeks}")
        return calibrate(played, simulations)
