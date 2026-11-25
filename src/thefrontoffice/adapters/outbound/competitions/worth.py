"""What a player is worth this week, as every competition reads it: recent form beside the outlook, nudged by usage.

Each competition says what its form, its outlook and its usage are — points a
game and a projection in football, a category line and minutes in basketball —
and this says how they combine, so the two read a player by one rule.
"""

from collections.abc import Sequence
from statistics import fmean

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


SLUMP_LABEL, HOT_LABEL = "Slump", "Hot"
"""What a player is called wherever he is shown — a drawer, a row's note, a model's player line, a to-do — whose last
few games ran well under what he was expected to give (`sustained`), or well over it."""

CALL_FORM = 0.75
"""Form's share of a form call, against the outlook's: `blend` weighs them evenly, which is what kept a slumping
player ahead of every streamer, and a hot one behind players he now outplays. A quarter stays with the outlook,
which still reads his week."""


def call(recent: float, ahead: float) -> float:
    """A form call: `CALL_FORM` of `recent` and the rest `ahead`, for a player whose games and outlook disagree by
    enough, for long enough (`sustained`)."""
    return CALL_FORM * recent + (1 - CALL_FORM) * ahead


def sustained(scored: Sequence[float], lines: Sequence[float], share: float, spare: int = 1) -> bool:
    """Whether a player's games ran past `share` of what each was expected to give — under it for a share below
    one, over it for one above — on average and in all but `spare` of them, his most telling game left out.

    One night is noise either way, so the run is read without its most telling game — his best for a run over, his
    worst for one under — and has to hold on average and game by game over the rest: one 27-point night is not a hot
    run, one zero not a slump.
    """
    if not scored or len(scored) != len(lines):
        return False
    over = share >= 1
    beyond = (lambda game, line: game > share * line) if over else (lambda game, line: game < share * line)
    games = list(zip(scored, lines, strict=True))
    if len(games) > 1:
        telling = max if over else min
        games.remove(telling(games, key=lambda pair: pair[0] - share * pair[1]))
    held = sum(beyond(game, line) for game, line in games)
    average = beyond(fmean(g for g, _ in games), fmean(line for _, line in games))
    return average and held >= len(games) - spare
