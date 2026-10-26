"""Building the inputs and outputs of the simulations by hand, so a test can say what they must conclude."""

from thefrontoffice.domain.models import Outcomes, PlayoffOdds

FEW = 2_000
"""Simulations enough to settle a clear case, few enough to keep the suite fast."""


def outcome(pid: str, *samples: float, plays: float = 1.0, floor: float = 0.0, remaining: float = 1.0) -> Outcomes:
    """One player's week drawn from `samples`, projected at their mean."""
    projection = sum(samples) / len(samples) if samples else 0.0
    return Outcomes(pid, pid.upper(), projection, samples, plays=plays, floor=floor, remaining=remaining)


def odds_split(win: float, loss: float) -> PlayoffOdds:
    """A playoff chance of one half overall, `win` with this week won and `loss` with it lost."""
    return PlayoffOdds(spots=6, playoffs=0.5, with_win=win, with_loss=loss, simulations=1)
