"""Facts about the NFL that the rest of the competition leans on, stated once.

Not decisions — the to-do list, the planner and the trade search make those —
but the vocabulary they share: how long a season is, and what a player's
designation means for whether he plays. Each had been defined beside its first
user and imported from there, so a planner read its injury rules out of the
to-do list's module.
"""

SEASON_WEEKS = 18
"""The NFL's regular season, in weeks: the furthest any fantasy season or projection runs."""

RULED_OUT = {
    "OUT": "is ruled out",
    "IR": "is on injured reserve",
    "PUP": "is on the PUP list",
    "SUS": "is suspended",
    "NA": "is not active",
    "DNR": "is not with a team",
}
"""Sleeper's designations for a player who will not play, in the words a person would use.

Questionable is deliberately absent: most questionable players play, and
flagging every one buries the starters who will not."""

LONG_TERM = frozenset({"IR", "PUP", "SUS", "NA", "DNR"})
"""Rulings that outlast a week. A plain Out is for one game: it covers next week at most,
and past that his projection, which Sleeper keeps publishing, is the better guess."""


def ruled_out(status: str) -> bool:
    """Whether a designation means he will not play this week."""
    return status.upper() in RULED_OUT
