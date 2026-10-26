"""Types for the Fantasy Premier League API.

The official game is a public read-only JSON API — no key, no OAuth — and it is
unusual in carrying both layers at once: the same payload that lists your squad
also carries Opta-derived expected goals and assists. Nothing here needs a
second stats provider the way the NBA path does.

Money is in tenths of a million throughout, the unit the API uses: a `now_cost`
of 40 is £4.0m. Converting on the way in would lose the exact arithmetic that
transfer affordability depends on, so it is converted only for display.
"""

from dataclasses import dataclass, field
from datetime import datetime

# element_type -> the abbreviation FPL shows in its own UI.
POSITIONS: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# How many of each position a legal starting eleven may hold. Also served by the
# API in `element_types`, but fixed by the rules of the game and needed to pick
# a lineup before any request has been made.
FORMATION_LIMITS: dict[str, tuple[int, int]] = {
    "GKP": (1, 1),
    "DEF": (3, 5),
    "MID": (2, 5),
    "FWD": (1, 3),
}

STARTING_SIZE = 11
SQUAD_SIZE = 15

# `status` on an element. Anything but "a" means the player may not play.
STATUS_LABELS: dict[str, str] = {
    "a": "",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not in squad",
}

MAX_FREE_TRANSFERS = 5
"""Free transfers roll over, capped at five. Not exposed by the public API."""

TRANSFER_HIT = 4
"""Points deducted per transfer beyond the free allowance."""


def as_millions(tenths: int) -> str:
    """Format an API money value for display: 105 -> '£10.5m'."""
    return f"£{tenths / 10:.1f}m"


@dataclass(frozen=True)
class Club:
    """One Premier League club, as the bootstrap names it."""

    short_name: str
    """Three letters, which is what a player carries and a table shows."""

    name: str
    """The club as a person says it: 'Tottenham Hotspur'."""

    code: int
    """The club's own id in the league's media library, which is what its crest
    is filed under — not the same number as `id`."""


@dataclass(frozen=True)
class Gameweek:
    """One of the 38 scoring periods."""

    id: int
    name: str
    deadline: datetime
    """Aware UTC. Transfers made after this do not count for the gameweek."""

    is_current: bool = False
    is_next: bool = False
    finished: bool = False
    average_score: int = 0


@dataclass(frozen=True)
class Player:
    """One footballer, as the game scores them."""

    id: int
    name: str
    """The short name FPL displays, e.g. 'Haaland'."""

    full_name: str
    """First and second name joined, for matching a name a user typed."""

    position: str
    team: str
    """Three-letter club abbreviation, e.g. 'ARS'."""

    cost: int
    """Current price in tenths of a million."""

    expected_points: float
    """The game's own projection for the next gameweek (`ep_next`)."""

    form: float
    points_per_game: float
    total_points: int
    selected_by: float
    """Ownership percentage across all managers — how differential a pick is."""

    status: str = "a"
    news: str = ""
    chance_of_playing: int | None = None
    """Percentage, or None when the game has published no doubt."""

    minutes: int = 0
    starts: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    saves: int = 0
    bonus: int = 0
    bonus_points: int = 0
    """BPS: the raw score bonus is awarded from, and a better form signal than
    bonus itself, which is capped at three per match."""

    yellow_cards: int = 0
    red_cards: int = 0

    penalties_order: int | None = None
    corners_order: int | None = None
    freekicks_order: int | None = None
    """Set-piece duty. None means not on them, which for an attacking returner
    is most of the difference between a good price and a bad one."""

    price_change: int = 0
    """This gameweek's move, in tenths of a million."""

    transfers_in: int = 0
    transfers_out: int = 0

    expected_goals: float = 0.0
    expected_assists: float = 0.0
    expected_goal_involvements: float = 0.0
    expected_goals_conceded: float = 0.0
    ict_index: float = 0.0

    code: int = 0
    """Opta's own id, which the photo CDN is keyed by. Distinct from `id`, the
    element number, which is reassigned between seasons."""

    @property
    def is_available(self) -> bool:
        return self.status == "a"

    @property
    def availability(self) -> str:
        """A short flag for the prompt, empty when the player is fully fit."""
        label = STATUS_LABELS.get(self.status, self.status)
        if self.chance_of_playing is not None and self.chance_of_playing < 100:
            return f"{label or 'doubt'} {self.chance_of_playing}%".strip()
        return label


@dataclass(frozen=True)
class Pick:
    """One of the fifteen slots in a manager's squad for a gameweek."""

    element: int
    position: int
    """1-11 are the starting eleven, 12-15 the bench in substitution order."""

    multiplier: int
    """0 on the bench, 1 starting, 2 captained, 3 under the triple-captain chip."""

    is_captain: bool = False
    is_vice_captain: bool = False

    @property
    def is_starting(self) -> bool:
        return self.position <= STARTING_SIZE


@dataclass(frozen=True)
class Squad:
    """A manager's fifteen for one gameweek, with the money behind it."""

    gameweek: int
    picks: list[Pick]
    bank: int
    """Unspent money in tenths of a million."""

    value: int
    """Squad value in tenths of a million, excluding the bank."""

    transfers_made: int = 0
    transfers_cost: int = 0
    points_on_bench: int = 0
    active_chip: str = ""

    @property
    def budget(self) -> int:
        """What a full rebuild could spend: the squad's value plus the bank."""
        return self.value + self.bank


@dataclass(frozen=True)
class GameweekResult:
    """One row of a manager's season history, used to derive free transfers."""

    event: int
    points: int
    transfers_made: int
    transfers_cost: int


@dataclass(frozen=True)
class MiniLeague:
    """A league the manager is in, of either format."""

    id: int
    name: str
    rank: int
    is_private: bool
    """FPL marks invitational leagues 'x' and its own global ones 's'."""

    rank_count: int | None = None
    """How many managers are in it. Absent for head-to-head, which ranks by
    match record rather than by position in a field."""

    is_h2h: bool = False
    """Head-to-head, where each gameweek is a fixture against one opponent
    rather than a placing among everyone. FPL keeps these in their own list,
    and a manager whose only private league is h2h has none in the other."""


@dataclass(frozen=True)
class Entry:
    """A manager's team."""

    entry_id: int
    name: str
    manager: str
    overall_points: int
    overall_rank: int
    current_event: int
    leagues: list[MiniLeague] = field(default_factory=list)


@dataclass(frozen=True)
class H2HMatch:
    """One head-to-head tie: who you are playing, and the score so far."""

    opponent_entry: int
    opponent_name: str
    my_points: int
    opponent_points: int


@dataclass(frozen=True)
class TableRow:
    """One entry in a mini-league table, of either format."""

    rank: int
    entry: int
    entry_name: str
    manager: str
    total: int
    """What the table is sorted on — league points in h2h, FPL points in classic."""

    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    points_for: int = 0
    """Only h2h tables carry this; in a classic league `total` is already it."""

    @property
    def record(self) -> str:
        """Empty for a classic league, which has no results to have a record of."""
        return f"{self.won}W {self.drawn}D {self.lost}L" if self.played else ""


@dataclass(frozen=True)
class Fixture:
    """One match, with the difficulty rating the game assigns each side."""

    event: int | None
    """None for a match not yet assigned to a gameweek."""

    home: str
    away: str
    home_difficulty: int
    away_difficulty: int
    kickoff: datetime | None = None

    def opponent_of(self, team: str) -> tuple[str, int, bool] | None:
        """Who `team` faces, at what difficulty, and whether they are at home."""
        if team == self.home:
            return self.away, self.home_difficulty, True
        if team == self.away:
            return self.home, self.away_difficulty, False
        return None


@dataclass(frozen=True)
class PastSeason:
    """What a player returned in a season that has finished.

    The season is over, so none of this can change again — which is why it is
    the one thing here worth caching for a day rather than an hour.
    """

    season: str
    """As FPL labels it, e.g. '2025/26'."""

    total_points: int
    minutes: int
    starts: int
    goals: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    saves: int
    bonus: int
    expected_goals: float
    expected_assists: float
    start_cost: int
    end_cost: int

    @property
    def points_per_game(self) -> float:
        """Per start rather than per appearance: a substitute cameo and a full
        ninety are not the same denominator, and starts is what FPL records."""
        return self.total_points / self.starts if self.starts else 0.0


@dataclass(frozen=True)
class LiveStat:
    """What one player has done in the gameweek being played.

    Minutes are here because zero points alone cannot be read: a player who
    blanked and a player whose match is on Sunday both sit at nought, and only
    one of them is bad news.
    """

    points: int
    minutes: int

    @property
    def has_played(self) -> bool:
        return self.minutes > 0


# The game's own names for the chips, and what a manager calls them.
CHIP_NAMES = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
    "manager": "Assistant Manager",
}


@dataclass(frozen=True)
class Chip:
    """One chip, and the window of gameweeks it can be played in.

    FPL splits the season in half and issues a set for each, so the same name
    appears twice with different windows — a Free Hit unused by GW19 is gone
    rather than carried forward.
    """

    name: str
    """The game's own key: 'freehit', 'bboost', '3xc', 'wildcard'."""

    start_event: int
    stop_event: int

    @property
    def label(self) -> str:
        return CHIP_NAMES.get(self.name, self.name.title())

    def covers(self, gameweek: int) -> bool:
        return self.start_event <= gameweek <= self.stop_event


@dataclass(frozen=True)
class ChipPlay:
    """A chip this manager has already spent, and the week they spent it."""

    name: str
    event: int
