"""Facts about the NFL that the rest of the competition leans on, stated once.

Not decisions — the to-do list, the planner and the trade search make those —
but the vocabulary they share: how long a season is, what a player's
designation means for whether he plays, which positions and slots a lineup is
made of, and what a scoring format is called. Each had been defined beside its
first user and imported from there, so a planner read its injury rules out of
the to-do list's module.
"""

import math

from thefrontoffice.adapters.outbound.competitions.nfl.model import LeagueRules, Scoring

SEASON_WEEKS = 18
"""The NFL's regular season, in weeks: the furthest any fantasy season or projection runs."""

TWO_WEEK_FINAL, TWO_WEEK_ROUNDS = 1, 2
"""Sleeper's `playoff_round_type` codes; 0, and any it adds later, is one week a round."""


def last_regular_week(rules: LeagueRules) -> int:
    """The regular season's last week: the one before `playoff_week_start`, or the NFL's last where the league sets none."""
    start = rules.playoff_week_start
    return start - 1 if start else SEASON_WEEKS


def _round_lengths(rules: LeagueRules) -> list[int]:
    """Each playoff round's length in weeks, first round first; empty where the league sets no bracket.

    A bracket of `playoff_teams` takes ceil(log2(teams)) rounds from `playoff_week_start`,
    each one week, or two where `playoff_round_type` says so (every round, or the final alone).
    """
    start, teams = rules.playoff_week_start, rules.playoff_teams
    if not start or not teams:
        return []
    rounds = math.ceil(math.log2(teams))
    lengths = [2 if rules.playoff_round_type == TWO_WEEK_ROUNDS else 1] * rounds
    if rules.playoff_round_type == TWO_WEEK_FINAL and lengths:
        lengths[-1] = 2
    return lengths


def season_end(rules: LeagueRules) -> int:
    """The league's last week: its championship's, or the NFL's last where it sets no bracket.

    Capped at the NFL's last week, which no fantasy week runs past.
    """
    if not rules.playoff_week_start or not rules.playoff_teams:
        return SEASON_WEEKS
    return min(SEASON_WEEKS, rules.playoff_week_start + sum(_round_lengths(rules)) - 1)


ROUND_NAMES = ("Final", "Semifinals", "Quarterfinals")
"""The bracket's last rounds, counted back from the final; any earlier is "Round N"."""


def playoff_round(rules: LeagueRules, week: int) -> str:
    """Which bracket round a week is — "Semifinals", "Final, week 1 of 2" — or empty for the regular season.

    Read from the same rounds `season_end` counts, so the two cannot disagree. A league
    that starts its playoffs but names no bracket size has no rounds to name: "Playoffs".
    """
    start = rules.playoff_week_start
    if not start or week < start:
        return ""
    if not rules.playoff_teams:
        return "Playoffs"
    lengths, first = _round_lengths(rules), start
    for index, length in enumerate(lengths):
        if week < first + length:
            from_end = len(lengths) - 1 - index
            name = ROUND_NAMES[from_end] if from_end < len(ROUND_NAMES) else f"Round {index + 1}"
            return f"{name}, week {week - first + 1} of {length}" if length > 1 else name
        first += length
    return ""  # past the final: no week the league plays


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


THIS_WEEK = frozenset({"QUESTIONABLE", "DOUBTFUL", "OUT"})
"""The injury report's own designations: this week's game, settled by Sunday's inactives.

A long ruling (IR, PUP, a suspension) is in every projection already; these
are the ones that move work between teammates on the day."""


RULED_OUT_SHORT = {
    "OUT": "out",
    "IR": "on IR",
    "PUP": "on PUP",
    "SUS": "suspended",
    "NA": "inactive",
    "DNR": "no team",
}
"""The same designations, short enough to stand where a row names his opponent."""


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


SCORING_NAMES: dict[Scoring, str] = {"pts_ppr": "PPR", "pts_half_ppr": "Half PPR", "pts_std": "Standard"}
"""The same, as a manager names it: the league's header, read by someone who knows what PPR means."""


def scoring_label(scoring: Scoring) -> str:
    """How a league scores, spelled out for the model."""
    return SCORING_LABELS[scoring]


def scoring_name(scoring: Scoring) -> str:
    """How a league scores, in the word its managers use."""
    return SCORING_NAMES[scoring]
