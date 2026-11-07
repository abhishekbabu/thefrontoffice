"""Facts about the NFL that the rest of the competition leans on, stated once.

Not decisions — the to-do list, the planner and the trade search make those —
but the vocabulary they share: how long a season is, what a player's
designation means for whether he plays, which positions and slots a lineup is
made of, and what a scoring format is called. Each had been defined beside its
first user and imported from there, so a planner read its injury rules out of
the to-do list's module.
"""

from thefrontoffice.adapters.outbound.competitions.nfl.model import Scoring

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
"""Rulings that outlast a week. A plain Out is for the coming game alone — the injury
report sets it for that week — and past it his projection, which Sleeper keeps publishing,
is the better guess."""


def ruled_out(status: str) -> bool:
    """Whether a designation means he will not play this week."""
    return status.upper() in RULED_OUT


def long_term(status: str) -> bool:
    """Whether a designation reaches past this week's game into the weeks ahead."""
    return status.upper() in LONG_TERM


def listed(status: str) -> bool:
    """Whether a designation is anything at all: a player cleared to play carries none, or Active."""
    return bool(status) and status.upper() != "ACTIVE"


STREAMED = frozenset({"K", "DEF"})
"""Positions managers fill from the wire week to week: a lineup starts one, and nobody holds a spare."""

FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})
"""What a fantasy league scores. A catalog carries every practice-squad body, and none is a waiver decision."""

FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}
"""Which positions a shared lineup slot accepts; any other slot takes only its own position."""

SCORING_LABELS: dict[Scoring, str] = {
    "pts_ppr": "Full PPR (1 point per reception)",
    "pts_half_ppr": "Half PPR (0.5 per reception)",
    "pts_std": "Standard (no point per reception)",
}


def scoring_label(scoring: Scoring) -> str:
    """How a league scores, as a person would say it."""
    return SCORING_LABELS[scoring]
