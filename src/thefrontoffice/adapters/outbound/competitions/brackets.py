"""A head-to-head playoff bracket in weeks: how many rounds, how long each, and what each is called.

Every head-to-head league runs the same single-elimination bracket from its
playoff start week; the platforms differ only in how they say how long a round
lasts, which each competition reads into `lengths` itself.
"""

import math

ROUND_NAMES = ("Final", "Semifinals", "Quarterfinals")
"""The bracket's last rounds, counted back from the final; any earlier is "Round N"."""


def lengths(teams: int, *, two_week_rounds: bool = False, two_week_final: bool = False) -> list[int]:
    """Each round's length in weeks, first round first; empty for a bracket of no teams.

    `teams` take ceil(log2(teams)) rounds — byes fill the first where it is not a
    power of two — each one week, or two for every round or for the final alone.
    """
    if teams < 2:
        return []
    rounds = [2 if two_week_rounds else 1] * math.ceil(math.log2(teams))
    if two_week_final:
        rounds[-1] = 2
    return rounds


def round_name(rounds: list[int], start: int, week: int) -> str:
    """Which round `week` falls in — "Semifinals", "Final, week 1 of 2" — or empty outside the bracket."""
    if week < start:
        return ""
    first = start
    for index, length in enumerate(rounds):
        if week < first + length:
            from_end = len(rounds) - 1 - index
            name = ROUND_NAMES[from_end] if from_end < len(ROUND_NAMES) else f"Round {index + 1}"
            return f"{name}, week {week - first + 1} of {length}" if length > 1 else name
        first += length
    return ""  # past the final: no week the league plays
