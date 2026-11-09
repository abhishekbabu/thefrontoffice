"""Types for the Sleeper API.

Sleeper is a public read-only API — no OAuth, no key, no per-user token. That
makes the football path much simpler than the Yahoo one: everything below is a
plain GET.
"""

from dataclasses import dataclass, field
from typing import Literal, get_args

from thefrontoffice.domain.models import record

ScoringFormat = Literal["pts_ppr", "pts_half_ppr", "pts_std"]

SCORING_FORMATS: tuple[ScoringFormat, ...] = get_args(ScoringFormat)

# Sleeper's lineup slots. FLEX and SUPER_FLEX accept several positions; BN and
# IR do not count toward a weekly score. Must equal the NFL rules' scored
# positions plus their flex slots; `competitions/nfl/test_rules.py` pins it.
STARTING_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "WRRB_FLEX", "REC_FLEX")


FREE_AGENT = "FA"
"""The club a player on no NFL roster is filed under. Sleeper sends none; the client fills in this."""


@dataclass(frozen=True)
class PlayerMeta:
    """The fields we keep from Sleeper's ~14MB player catalog, every one present and typed."""

    player_id: str
    name: str
    position: str = ""
    team: str = FREE_AGENT
    status: str = ""
    injury_status: str = ""
    depth_chart_order: int = 0
    years_exp: int = 0
    age: int = 0
    college: str = ""
    number: int = 0
    injury_body_part: str = ""
    injury_notes: str = ""


@dataclass(frozen=True)
class SeasonState:
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
    playoff_teams: int = 0
    """How many teams the regular season sends to the playoffs. Zero where unknown."""
    playoff_week_start: int = 0
    """The first playoff week; the regular season is every week before it. Zero where unknown."""
    scoring_rules: dict[str, float] = field(default_factory=dict)
    """Points per unit of each stat, as the league set them — what Sleeper's own app prices a line by.
    Empty where unknown, and a line is then read at Sleeper's published figure for the format."""
    ir_allows: frozenset[str] = frozenset({"IR"})
    """The designations the league's injured-reserve slot takes, upper-cased. A player on IR whose
    designation is no longer among them locks the roster: Sleeper refuses every move until he leaves it."""

    @property
    def roster_spots(self) -> int:
        """How many players the roster holds outside its reserve and taxi slots: starters and bench."""
        return sum(1 for s in self.roster_positions if s not in ("IR", "TAXI"))

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
    reserve_ids: list[str] = field(default_factory=list)
    """Players in injured-reserve or taxi slots: on the roster, but not taking a spot on it."""
    ir_ids: list[str] = field(default_factory=list)
    """The injured-reserve slots alone, taxi left out."""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0

    @property
    def record(self) -> str:
        return record(self.wins, self.losses, self.ties)


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


EMPTY_SLOT = "0"
"""How Sleeper fills a starting slot nobody is in."""


@dataclass(frozen=True)
class SleeperMatchup:
    """One team's side of a week's matchup: who it plays, what it has scored, and the lineup it set.

    The lineup is the week's own, which the roster's copy can lag by days.
    """

    roster_id: int
    matchup_id: int | None
    """Shared by the two teams playing each other; None where the team has nobody this week."""
    points: float = 0.0
    starters: list[str] = field(default_factory=list)
    """Positionally aligned with the league's starting slots; an empty slot is an empty string."""
    players_points: dict[str, float] = field(default_factory=dict)
    """What each of the team's players has scored this week."""


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

# What a football game line is kept for: the points in each scoring format,
# and the usage behind them. Snaps against the team's snaps is a share no
# single row states; targets and carries are what a projection is built from.
# The box score beside them is what a game log reads, and `gp` is what says a
# kicker or a defense took the field, having no offensive snaps to count.
NFL_LINE_KEYS = (
    "pts_ppr",
    "pts_half_ppr",
    "pts_std",
    "gp",
    "off_snp",
    "tm_off_snp",
    "pass_cmp",
    "pass_att",
    "pass_yd",
    "pass_td",
    "pass_int",
    "rush_att",
    "rush_yd",
    "rush_td",
    "rec_tgt",
    "rec",
    "rec_yd",
    "rec_td",
    "fgm",
    "fga",
    "xpm",
    "xpa",
    "pts_allow",
    "sack",
    "int",
    "fum_rec",
    "td",
)


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
