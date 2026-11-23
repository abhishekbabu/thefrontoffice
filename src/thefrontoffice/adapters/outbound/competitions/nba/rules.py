"""The nine categories a basketball league is scored on, defined once.

Each category is named in four places — Sleeper's box score (recent form,
projections), Yahoo's stat ids (the scout's leaders, the matchup), the label a
page shows and the tag a prompt line carries — and every one of them reads it
from here, so a category cannot be spelled two ways and miss its own figure.

Beside them, the other facts every basketball reader shares: the clock the
league keeps, the injured slots and the statuses that rule a player out.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from thefrontoffice.adapters.outbound.competitions.availability import QUESTIONABLE
from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.injuries import in_words
from thefrontoffice.adapters.outbound.competitions.nba.model import INJURED_SLOTS as INJURED_SLOTS
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.domain.models import Better

PACIFIC = ZoneInfo("America/Los_Angeles")
"""The league schedules by Pacific, so a day boundary is decided there rather
than on whatever clock this happens to be running on."""


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

    better: Better = "higher"
    """Which way a line improves in it: fewer turnovers, more of everything else."""

    yahoo_shots: str = ""
    """For a percentage, Yahoo's stat id for makes over attempts, which a matchup prints '109/218'."""

    attempted: str = ""
    """For a percentage, the label its attempts a game carry in a `Line`: 'FGA'. What weights the rate by volume."""

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
FIELD_GOALS = Category("FG%", "5", "fgm", "FG", attempts="fga", yahoo_shots="9004003", attempted="FGA")
FREE_THROWS = Category("FT%", "8", "ftm", "FT", attempts="fta", yahoo_shots="9007006", attempted="FTA")
TURNOVERS = Category("TO", "19", "to", "to", better="lower")

CATEGORIES = (POINTS, REBOUNDS, ASSISTS, STEALS, BLOCKS, THREES, FIELD_GOALS, FREE_THROWS, TURNOVERS)
"""What a nine-category league is scored on, in the order it is read."""

SCOUTED = tuple(category for category in CATEGORIES if category is not TURNOVERS)
"""The categories worth finding a free agent for: leading the league in
turnovers is not a reason to add anybody."""

BOX_SCORE = tuple(dict.fromkeys(key for c in CATEGORIES for key in (c.made, c.attempts) if key))
"""Every Sleeper box-score key the categories are built from."""

NOT_TAKEN: dict[str, frozenset[str]] = {
    "IL": frozenset({"", "DTD", "GTD"}),
    "IL+": frozenset({""}),
}
"""What each injured slot will not hold, by Yahoo status: IL takes Out, Injured and Out For
Season, IL+ also day-to-day and game-time decisions. Listed as what is refused rather than what is
taken, so a status Yahoo's rules do not mention is never flagged — a false "move him" costs
more than a late one. Empty is a player with nothing reported: cleared to play."""


def stranded(slot: str, status: str) -> bool:
    """Whether a player sits in an injured slot his status no longer qualifies him for."""
    return status.upper() in NOT_TAKEN.get(slot.upper(), frozenset())


SLOT_TAKES: dict[str, frozenset[str]] = {
    "G": frozenset({"PG", "SG"}),
    "F": frozenset({"SF", "PF"}),
    "GF": frozenset({"PG", "SG", "SF", "PF"}),
    "G/F": frozenset({"PG", "SG", "SF", "PF"}),
    "FC": frozenset({"SF", "PF", "C"}),
    "F/C": frozenset({"SF", "PF", "C"}),
}
"""The positions each combined lineup slot takes; any other slot takes its own position, and
`UTIL` takes anybody. Yahoo prints a player's eligibility as 'PG,SG'."""

ANYBODY = "UTIL"
"""The lineup slot any active player may fill."""


def fits(slot: str, positions: str) -> bool:
    """Whether a player eligible at `positions` ('PG,SG') may fill lineup slot `slot`."""
    slot = slot.upper()
    held = eligible(positions)
    if slot == ANYBODY:
        return bool(held)
    return bool(held & SLOT_TAKES.get(slot, frozenset({slot})))


POSITIONS = ("PG", "SG", "SF", "PF", "C")
"""Basketball's five positions, in the order a filter offers them."""

FILTER_SLOTS = ("G", "F")
"""The combined slots a filter offers too, where the league has them in its lineup."""


def eligible(positions: str) -> frozenset[str]:
    """Each position a player is eligible at, from Yahoo's 'PG,SG'."""
    return frozenset(p.strip().upper() for p in positions.split(",") if p.strip())


def position_filters(players: Iterable[Player], slots: Sequence[str]) -> dict[str, frozenset[str]]:
    """The position filters a list of players offers, each with the eligibilities it keeps.

    One per position anybody in `players` is eligible at, rather than one per
    combination Yahoo prints ('PG,SG', 'SF,PF,C'), each keeping everyone eligible
    there; then 'G' and 'F' where the league's lineup `slots` have them, each
    keeping anybody who could fill it (`SLOT_TAKES`).
    """
    held = frozenset().union(*(eligible(p.position) for p in players))
    single = {position: frozenset({position}) for position in POSITIONS if position in held}
    combined = {slot: SLOT_TAKES[slot] for slot in FILTER_SLOTS if slot in {s.upper() for s in slots}}
    return {**single, **combined}


RULED_OUT = frozenset({"O", "INJ", "SUSP", "IL", "IL+", "NA"})
"""Yahoo's statuses for a player who will not play: out, injured, suspended, on
the injured list, not active. Game-time and day-to-day decisions are absent —
those players mostly play, and flagging them as out buries the ones who will not."""


def ruled_out(status: str) -> bool:
    """Whether a Yahoo status means he will not play."""
    return status.upper() in RULED_OUT


CLAIM_LAG = timedelta(days=0)
"""How long after the day he clears waivers a claimed player's games count from: none, he plays that night.

Yahoo's `waiver_date` is the day a claim processes, overnight, before any
game: GM 3 (478.l.69598, `waiver_type` R, `waiver_time` 2) put Georges Niang,
dropped Sun 22 Nov 2026, on waivers clearing Wed 25 Nov — Mon and Tue waiting,
the period starting "the following day" (help.yahoo.com/kb/SLN8367.html) —
and its one claim this season, Precious Achiuwa, processed 01:31 PT on Thu 29
Oct and started at C that night for 24 points. Its lineups are daily and
`intraday`, which Yahoo's deadlines page reads as "Today roster changes - No
deadline; rosters update immediately after a transaction"
(help.yahoo.com/kb/SLN6775.html), so a player on the roster by morning can
be slotted for that night.
"""


def playable_from(player: Player) -> date | None:
    """The first day a player on waivers can play for whoever claims him (`CLAIM_LAG`); None for anyone else."""
    return player.waiver_date + CLAIM_LAG if player.waiver_date else None


def clears(player: Player, priority: int = 0) -> str:
    """'Waivers · clears Wed 25 Nov' for a player on waivers, with your waiver `priority` where known —
    '… · you're #7' — since a claim goes to whoever claims him first in that order; empty for anyone else."""
    cleared = player.waiver_date
    if not cleared:
        return ""
    return f"Waivers · clears {weekday_day_month(cleared)}" + (f" · you're #{priority}" if priority else "")


GAME_TIME = frozenset({"GTD", "DTD", "Q"})
"""Yahoo's statuses for a player who may yet play: a game-time decision, day-to-day, questionable."""

STATUS_WORDS = {
    "O": "Out",
    "INJ": "Injured",
    "SUSP": "Suspended",
    "IL": "Injured list",
    "IL+": "Injured list+",
    "NA": "Not active",
    "GTD": "Game-time decision",
    "DTD": "Day-to-day",
    "Q": "Questionable",
}
"""Yahoo's status codes in words (`injuries.in_words`)."""


def status_word(status: str) -> str:
    """A Yahoo status as a person would say it, 'O' as 'Out'; a code it does not know, as Yahoo wrote it."""
    return in_words(status, STATUS_WORDS)


def chance(status: str) -> float:
    """The chance he plays his next game: discounted for a game-time decision (`availability.QUESTIONABLE`), else
    whole. A ruling is not a chance: his games already start from his return."""
    return QUESTIONABLE if status.upper() in GAME_TIME else 1.0


Line = dict[str, float]
"""Figures keyed by category label, and each percentage's attempts a game by its `Category.attempted`.
A category with no figure is absent."""


def line(totals: Mapping[str, float], games: int = 1) -> Line:
    """Every category's figure over summed box scores, keyed by label, with each percentage's attempts a game.

    The attempts ride along because a rate alone says nothing of its weight: a
    player going 2 for 3 moves a team's FG% far less than one going 10 for 15.
    """
    figures = {c.label: value for c in CATEGORIES if (value := c.figure(totals, games)) is not None}
    tried = {
        c.attempted: totals.get(c.attempts, 0.0) / games for c in CATEGORIES if c.is_percentage and c.label in figures
    }
    return figures | (tried if games else {})


COUNTED = {c.yahoo_stat: c for c in CATEGORIES if not c.is_percentage}
"""The counting categories by Yahoo stat id: what a points league's weights can multiply."""


def fantasy_points(figures: Mapping[str, float], weights: Mapping[str, float]) -> float | None:
    """A points league's score for a line: each counting category's figure times its weight, summed.

    Per game for a per-game line, a total for a projected one. `weights` is keyed by Yahoo stat
    id, as the league's settings give them. None for an empty line, and for a league weighting
    a stat no category here counts (field goals attempted, double-doubles): a sum missing one
    of its terms would read as the real score.
    """
    if not figures or not weights or any(stat not in COUNTED for stat in weights):
        return None
    return sum(weight * figures.get(COUNTED[stat].label, 0.0) for stat, weight in weights.items())


def printed(stats: Mapping[str, str], category: Category) -> tuple[float, float]:
    """A category's figure on a Yahoo scoreboard as numbers: its total and nought, or a percentage's makes and
    attempts from the '109/218' Yahoo prints beside it. A figure not yet printed — a dash — is nothing scored."""
    if category.is_percentage:
        made, _, taken = stats.get(category.yahoo_shots, "").partition("/")
        return amount(made), amount(taken)
    return amount(stats.get(category.yahoo_stat, "")), 0.0


def amount(figure: str) -> float:
    """A figure as Yahoo prints it, as a number; nothing printed is nothing scored."""
    try:
        return float(figure)
    except ValueError:
        return 0.0
