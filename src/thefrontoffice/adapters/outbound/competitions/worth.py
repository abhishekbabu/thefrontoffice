"""What a player is worth this week, as every competition reads it: recent form beside the outlook, nudged by usage.

Each competition says what its form, its outlook and its usage are — points a
game and a projection in football, a category line and minutes in basketball —
and this says how they combine, so the two read a player by one rule.
"""

from collections.abc import Sequence

FORM_WEIGHT = 0.5
"""The share of a player's worth that is his recent form; the rest is his outlook.

Worth = (FORM_WEIGHT × form + (1 − FORM_WEIGHT) × outlook) × usage, either alone
where the other is unknown. Even weights: an outlook alone drops a player in
form whenever one week's matchup or schedule dents his number, and form alone
chases one big night.
"""

USAGE_SWING = 0.1
"""The most usage moves a worth, either way: a tenth.

Points follow playing time, and a role that is steady says more about next week
than one that swings. So a player on a steady large share of the game in every
one of his last few is worth a tenth more; one whose share moved by a jump that
counts between them, and not because his role grew, a tenth less. A tenth
because it is a tiebreak between comparable players, not a ranking of its own.
"""


def blend(recent: float | None, ahead: float | None) -> float | None:
    """`FORM_WEIGHT` of `recent` and the rest `ahead`; either alone where the other is unknown, None with neither."""
    if recent is None:
        return ahead
    if ahead is None:
        return recent
    return FORM_WEIGHT * recent + (1 - FORM_WEIGHT) * ahead


def settled(games: int, settling: int) -> float:
    """How much `games` in a new role count against what was read of him before: `games / (games + settling)`.

    `settling` is the games it takes before the new role counts for as much as
    the old reading, so one big night after a jump in playing time moves a
    player a fraction as far as a role long settled: a hot week is as often
    that as a new role.
    """
    return games / (games + settling) if games > 0 else 0.0


def usage(readings: Sequence[float], *, steady_from: float, swings_by: float, fewest: int, grew: bool = False) -> float:
    """What a player's usage over his last games multiplies his worth by: 1 ± `USAGE_SWING`, or 1.

    `readings` are his share of the game, oldest first: snaps, minutes. At least
    `steady_from` in every one is steady; a gap of `swings_by` between his most
    and least is a swing, unless his role grew — `grew`, or his latest game is
    his most of them, since a debut ramping up has too few games for a trend.
    Fewer than `fewest` readings say nothing.
    """
    if len(readings) < fewest:
        return 1.0
    if min(readings) >= steady_from:
        return 1 + USAGE_SWING
    grew = grew or readings[-1] == max(readings)
    if not grew and max(readings) - min(readings) >= swings_by:
        return 1 - USAGE_SWING
    return 1.0
