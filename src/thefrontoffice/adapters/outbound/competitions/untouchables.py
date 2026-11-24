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
