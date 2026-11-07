"""The nine categories a basketball league is scored on, defined once.

Each category is named in four places — Sleeper's box score (recent form,
projections), Yahoo's stat ids (the scout's leaders, the matchup), the label a
page shows and the tag a prompt line carries — and every one of them reads it
from here, so a category cannot be spelled two ways and miss its own figure.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    """One scoring category, as each platform and each reader names it."""

    label: str
    """What a page and the model call it: 'PTS', 'FG%'."""

    yahoo_stat: str
    """Yahoo's stat id, which a player sort and a matchup's team stats key by."""

    made: str
    """Sleeper's box-score key; for a percentage, the makes."""

    tag: str
    """How a prompt line marks it: after a count ('25.0p'), before a percentage ('FG48.0%')."""

    attempts: str = ""
    """Sleeper's attempts key, which makes this a percentage."""

    @property
    def is_percentage(self) -> bool:
        return bool(self.attempts)

    def figure(self, totals: Mapping[str, float], games: int = 1) -> float | None:
        """This category over summed box scores: a count per `games`, or a percentage.

        A percentage is summed makes over summed attempts rather than an average
        of per-game percentages — the two differ whenever attempts vary, which
        is exactly when it matters. Nothing attempted is no percentage at all,
        which is a different thing from 0%.
        """
        if self.is_percentage:
            attempted = totals.get(self.attempts, 0.0)
            return totals.get(self.made, 0.0) / attempted if attempted else None
        return totals.get(self.made, 0.0) / games if games else None

    def show(self, value: float) -> str:
        """The figure as a person reads it: '25.3', '48.2%'."""
        return f"{value:.1%}" if self.is_percentage else f"{value:.1f}"

    def tagged(self, value: float) -> str:
        """The figure as a prompt line carries it: '25.3p', 'FG48.2%'."""
        return f"{self.tag}{self.show(value)}" if self.is_percentage else f"{self.show(value)}{self.tag}"


POINTS = Category("PTS", "12", "pts", "p")
REBOUNDS = Category("REB", "15", "reb", "r")
ASSISTS = Category("AST", "16", "ast", "a")
STEALS = Category("STL", "17", "stl", "s")
BLOCKS = Category("BLK", "18", "blk", "b")
# Tagged `tpm`, not `3pm`: "5" and "3pm" read as "53pm", to the model as to a person.
THREES = Category("3PTM", "10", "tpm", "tpm")
FIELD_GOALS = Category("FG%", "5", "fgm", "FG", attempts="fga")
FREE_THROWS = Category("FT%", "8", "ftm", "FT", attempts="fta")
TURNOVERS = Category("TO", "19", "to", "to")

CATEGORIES = (POINTS, REBOUNDS, ASSISTS, STEALS, BLOCKS, THREES, FIELD_GOALS, FREE_THROWS, TURNOVERS)
"""What a nine-category league is scored on, in the order it is read."""

SCOUTED = tuple(category for category in CATEGORIES if category is not TURNOVERS)
"""The categories worth finding a free agent for: leading the league in
turnovers is not a reason to add anybody."""

BOX_SCORE = tuple(dict.fromkeys(key for c in CATEGORIES for key in (c.made, c.attempts) if key))
"""Every Sleeper box-score key the categories are built from."""

INJURED_SLOTS = frozenset({"IL", "IL+"})
"""Roster slots that hold an injured player outside the active roster."""

RULED_OUT = frozenset({"O", "INJ", "SUSP", "IL", "IL+", "NA"})
"""Yahoo's statuses for a player who will not play: out, injured, suspended, on
the injured list, not active. Game-time and day-to-day decisions are absent —
those players mostly play, and flagging them as out buries the ones who will not."""


def ruled_out(status: str) -> bool:
    """Whether a Yahoo status means he will not play."""
    return status.upper() in RULED_OUT


Line = dict[str, float]
"""Figures keyed by category label. A category with no figure is absent."""


def line(totals: Mapping[str, float], games: int = 1) -> Line:
    """Every category's figure over summed box scores, keyed by label."""
    return {c.label: value for c in CATEGORIES if (value := c.figure(totals, games)) is not None}
