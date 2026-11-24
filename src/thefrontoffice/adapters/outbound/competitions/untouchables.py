"""How a prompt tells the model which of your players are untouchable: one note, alike in every competition.

The choosers of drops, trades and transfers already leave them alone; the
model is told as well, so it argues the week without letting them go, and the
scouting engine drops any move of its that does regardless (`CompetitionContext.untouchable`).
"""

from collections.abc import Collection


def note(names: Collection[str]) -> list[str]:
    """The line naming who is untouchable; none where nobody is, so a prompt without one reads as it did."""
    if not names:
        return []
    return [
        f"Untouchable — the manager's to keep, whatever the figures; never suggest dropping, trading or selling: "
        f"{', '.join(sorted(names))}."
    ]


def given(names: Collection[str]) -> list[str]:
    """The line saying a proposed trade gives away untouchables; none where it gives none.

    The manager proposed it, so it is not refused: the model is told to say so
    plainly and weigh whether what comes back is worth breaking the mark.
    """
    if not names:
        return []
    return [
        f"This trade gives away players the manager marked untouchable: {', '.join(sorted(names))}. "
        "Say so plainly in the verdict, and weigh whether the return is worth breaking that."
    ]
