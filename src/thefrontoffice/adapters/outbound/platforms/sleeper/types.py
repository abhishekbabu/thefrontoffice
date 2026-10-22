"""Types for the Sleeper API.

Sleeper is a public read-only API — no OAuth, no key, no per-user token. That
makes the football path much simpler than the Yahoo one: everything below is a
plain GET.
"""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

ScoringFormat = Literal["pts_ppr", "pts_half_ppr", "pts_std"]

# Sleeper's lineup slots. FLEX and SUPER_FLEX accept several positions; BN and
# IR do not count toward a weekly score.
STARTING_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "WRRB_FLEX", "REC_FLEX")

FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


class PlayerMeta(TypedDict, total=False):
    """The fields we keep from Sleeper's ~14MB player catalog."""

    player_id: str
    name: str
    position: str
    team: str
    status: str
    injury_status: str
    depth_chart_order: int
    years_exp: int
    age: int
    college: str
    number: int
    injury_body_part: str
    injury_notes: str


@dataclass(frozen=True)
class SeasonState:
    """Where a sport's season currently is."""

    week: int
    season: str
    season_type: str

    @property
    def is_regular_season(self) -> bool:
        return self.season_type == "regular"


@dataclass(frozen=True)
class SleeperUser:
    user_id: str
    username: str
    display_name: str


@dataclass(frozen=True)
class SleeperLeague:
    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_format: ScoringFormat
    roster_positions: list[str] = field(default_factory=list)
    trade_deadline: int = 0
    """The last week trades are accepted. Zero where the league set none."""

    @property
    def starting_slots(self) -> list[str]:
        """Lineup slots that score, in the order Sleeper lists them."""
        return [s for s in self.roster_positions if s in STARTING_SLOTS]


@dataclass(frozen=True)
class SleeperRoster:
    roster_id: int
    owner_id: str
    player_ids: list[str]
    starter_ids: list[str]
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0

    @property
    def record(self) -> str:
        base = f"{self.wins}-{self.losses}"
        return f"{base}-{self.ties}" if self.ties else base


@dataclass(frozen=True)
class WeeklyProjection:
    """A weekly projection for one player."""

    player_id: str
    name: str
    position: str
    team: str
    opponent: str
    points: float
    injury_status: str = ""
    stats: dict[str, float] = field(default_factory=dict)
    """The projection broken out — passing yards, receptions, targets. The total
    is what a lineup is chosen on; this is what makes the total believable."""

    @property
    def is_questionable(self) -> bool:
        return bool(self.injury_status) and self.injury_status.upper() not in ("", "ACTIVE")


@dataclass(frozen=True)
class TrendingPlayer:
    player_id: str
    count: int


@dataclass(frozen=True)
class GameProjection:
    """A projection for one player in one game.

    Basketball projections are per game rather than per week, so a category
    league sums a player's games inside the matchup period to get the totals it
    scores on. The schedule falls out of the same data: four rows means four
    games.
    """

    player_id: str
    name: str
    team: str
    opponent: str
    date: str
    """ISO date of the game, used to select the games inside a matchup period."""
    stats: dict[str, float]


# The stats worth keeping from a season row. Sleeper sends ~70 per player
# across 8k players; the rest are kicking splits and defensive counting stats
# that no fantasy page reads.
SEASON_STAT_KEYS = (
    "gp",
    "pts_ppr",
    "pts_half_ppr",
    "pts_std",
    "pos_rank_ppr",
    "pass_yd",
    "pass_td",
    "pass_int",
    "cmp_pct",
    "rush_yd",
    "rush_td",
    "rec",
    "rec_yd",
    "rec_td",
    "rec_tgt",
)


# The production splits, as opposed to the totals and ranks that get their own
# field on SeasonStats.
SPLIT_KEYS = tuple(k for k in SEASON_STAT_KEYS if k not in ("gp", "pos_rank_ppr") and not k.startswith("pts_"))


@dataclass(frozen=True)
class SeasonStats:
    """What a player actually did over a season, as opposed to was projected to.

    Held per scoring format because a league's own currency is the only one
    worth showing: 75 receptions is 37.5 points of difference between full and
    standard, which is the gap between a flex and a starter.
    """

    player_id: str
    season: str
    games: int
    points: dict[str, float]
    position_rank: int
    splits: dict[str, float]

    def scored(self, scoring: ScoringFormat) -> float:
        return self.points.get(scoring, 0.0)

    def per_game(self, scoring: ScoringFormat) -> float:
        """The number a season is actually judged on — a total rewards
        availability, and a player who missed six weeks is not worse per week
        for it."""
        return self.scored(scoring) / self.games if self.games else 0.0


@dataclass(frozen=True)
class ScheduledGame:
    """One real-world NFL game, from Sleeper's own season schedule."""

    week: int
    date: str
    """ISO date. Sleeper publishes the day, not the kickoff time."""

    home: str
    away: str
    status: str = ""

    def opponent_of(self, team: str) -> tuple[str, bool] | None:
        """Who `team` plays that week, and whether they are at home."""
        if team == self.home:
            return self.away, True
        if team == self.away:
            return self.home, False
        return None


@dataclass(frozen=True)
class Transaction:
    """One completed move by somebody in the league."""

    kind: str
    """waiver, free_agent or trade, as Sleeper labels it."""

    roster_ids: list[int]
    adds: dict[str, int]
    """player_id -> the roster that gained them."""

    drops: dict[str, int]
    when: int = 0
    """Epoch milliseconds, which is a number until somebody formats it."""


# The nine-category box score, as Sleeper keys it. Absent means zero: no key
# here is ever published as an explicit 0, and the minimum published value is
# 1 — verified across a full week of real game logs.
NBA_STAT_KEYS = ("pts", "reb", "ast", "stl", "blk", "to", "tpm", "fgm", "fga", "ftm", "fta")

# Sleeper files team totals in the same feed as players, under a prefixed id.
TEAM_ROW_PREFIX = "TEAM_"

# What a fantasy league actually scores. The catalog carries every practice
# squad body in the league, and none of them are a waiver decision.
FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})

# What a football game line is kept for: the points in each scoring format,
# and the usage behind them. Snaps against the team's snaps is a share no
# single row states; targets and carries are what a projection is built from.
NFL_LINE_KEYS = ("pts_ppr", "pts_half_ppr", "pts_std", "off_snp", "tm_off_snp", "rec_tgt", "rush_att")


@dataclass(frozen=True)
class NFLGameLine:
    """One player's line from one football game.

    Carries the club and opponent of that game rather than of today: a
    player traded in week 5 scored his week-3 points for somebody else, and
    against somebody else.
    """

    player_id: str
    week: int
    team: str
    opponent: str
    position: str
    stats: dict[str, float]


@dataclass(frozen=True)
class NBAGameLog:
    """One player's line from one basketball game.

    Per game rather than per week, which is what makes a "last ten" window
    mean ten games rather than three weeks of uneven ones.
    """

    player_id: str
    date: str
    """ISO date of the game, and what a run of games is ordered by."""

    opponent: str
    stats: dict[str, float]

    def get(self, key: str) -> float:
        """A category, treating an absent key as the nought it stands for."""
        return self.stats.get(key, 0.0)
