"""How a simulated score is read, the same way by every simulation: a result, and a point in a range."""

from collections.abc import Sequence

from thefrontoffice.domain.models import Outcome, outcome

WORTH: dict[Outcome, float] = {"won": 1.0, "drawn": 0.5, "lost": 0.0}


def result(mine: float, theirs: float) -> float:
    """What a result adds to a record: a win, half for a tie, nothing for a loss."""
    return WORTH[outcome(mine, theirs)]


def quantile(ordered: Sequence[float], share: float) -> float:
    """The value `share` of the way up `ordered`, which must be sorted and not empty."""
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]
