"""How the simulations' chances and ranges held up against what then happened."""

from collections.abc import Sequence
from typing import Literal, get_args

from pydantic import BaseModel, Field


class CalibrationBucket(BaseModel):
    """Matchups the simulation gave a similar chance, and how often that side won."""

    low: float
    high: float
    matchups: int
    predicted: float
    won: float


class RangeScore(BaseModel):
    """How well players' ranges held what they then scored."""

    players: int = Field(description="Player-games scored.")
    inside: float = Field(description="Share whose score fell between the 10th and 90th percentile: 0.8 if right.")
    below: float = Field(description="Share below the 10th percentile: 0.1 if right.")
    above: float = Field(description="Share above the 90th percentile: 0.1 if right.")
    loss: float = Field(
        description="Mean quantile loss across the deciles, in points: lower is a sharper, truer range."
    )


class Calibration(BaseModel):
    """How the simulation's chances compared with what happened."""

    matchups: int
    brier: float = Field(description="Mean squared error of the chances; 0 is perfect, 0.25 is a coin flip.")
    buckets: list[CalibrationBucket] = Field(default_factory=list)


def calibration(called: Sequence[tuple[float, float]], width: float = 0.2) -> Calibration:
    """How a run of chances compared with what happened: each a chance and its result, one for won, nought for
    lost, a half for level — scored, and bucketed `width` apart by the chance given."""
    if not called:
        return Calibration(matchups=0, brier=0.0)
    edges = round(1 / width)
    buckets = []
    for step in range(edges):
        low, high = round(step * width, 9), round((step + 1) * width, 9)
        inside = [(c, o) for c, o in called if low <= c < high or (step == edges - 1 and c >= high)]
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
    return Calibration(matchups=len(called), brier=sum((c - o) ** 2 for c, o in called) / len(called), buckets=buckets)


OddsModel = Literal["hand-set", "fitted, independent", "fitted"]
"""The spreads a category league's odds can be checked under: those set by hand before any fit, the fitted
ones with every category taken as independent, and the fitted ones as the app runs them."""

ODDS_MODELS: tuple[OddsModel, ...] = get_args(OddsModel)


class OddsFit(BaseModel):
    """How far a category league's weeks strayed from what their games projected, over a season played."""

    season: str
    player_weeks: int = Field(description="Weeks of rostered-calibre players the fit is read from.")
    missed: float = Field(description="Share of their clubs' games those players sat out.")
    form: dict[str, float] = Field(description="Spread of a factor on a player's week in each count, by label.")
    rate: dict[str, float] = Field(description="The same on each percentage's makes, by label.")
    game: dict[str, float] = Field(description="One game's spread around a player's average, as a share of it.")
    typical: dict[str, float] = Field(description="A rostered player's game: a count's average, a percentage's rate.")
    kept: dict[str, float] = Field(
        description="The share of a player's distance from the typical game that his weeks bore out."
    )
    correlation: dict[str, dict[str, float]] = Field(
        description="How each category's miss moves with each other's, summed over a roster's players."
    )
    loadings: dict[str, float] = Field(description="Each category's share in the one swing they move with.")


class OddsCheck(BaseModel):
    """How one set of spreads called the categories and weeks of a season played, in leagues dealt from it."""

    season: str
    model: OddsModel
    weeks: int
    categories: Calibration = Field(description="Each category of each matchup, bucketed a tenth apart.")
    matchups: Calibration = Field(description="Each matchup's week, a level week a half.")
