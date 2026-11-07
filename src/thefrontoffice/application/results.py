"""How a simulated score is read, the same way by every simulation: a result, and a point in a range."""

from collections.abc import Sequence


def result(mine: float, theirs: float) -> float:
    """What a result adds to a record: a win, half for a tie, nothing for a loss."""
    return 1.0 if mine > theirs else 0.5 if mine == theirs else 0.0


def quantile(ordered: Sequence[float], share: float) -> float:
    """The value `share` of the way up `ordered`, which must be sorted and not empty."""
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]
