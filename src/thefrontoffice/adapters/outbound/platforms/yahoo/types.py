"""Yahoo Fantasy API type definitions.

What the client reads out of Yahoo's responses, once, so nothing beyond this
package touches the SDK's objects — which get their attributes by `setattr` at
runtime and promise none of them.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from thefrontoffice.domain.models import record


class PlayerStatus(StrEnum):
    """Yahoo API player status filter values."""

    ALL_AVAILABLE = "A"
    FREE_AGENT = "FA"
    WAIVERS = "W"
    TAKEN = "T"
    KEEPERS = "K"


class PlayerStat(StrEnum):
    """Yahoo API sort fields that are not a stat.

    A sport's own stat ids sort too, and belong to that sport's rules.
    """

    OVERALL_RANK = "OR"
    ACTUAL_RANK = "AR"
    FANTASY_POINTS = "PTS"
    NAME = "NAME"


class Timeframe(StrEnum):
    """Yahoo API time window values for sorting."""

    SEASON = "season"
    DATE = "date"
    LAST_WEEK = "lastweek"
    LAST_MONTH = "lastmonth"


class Average(StrEnum):
    """The spans Yahoo averages a player's line over, as a `stats;type=` asks for them: per game, as its pages show."""

    SEASON = "average_season"
    LAST_MONTH = "average_lastmonth"


@dataclass(frozen=True)
class YahooLine:
    """A player's line over some span, as Yahoo prints it."""

    stats: dict[str, str] = field(default_factory=dict)
    """Yahoo stat id -> its figure: '15.7', '.536', '6.0/11.2'; '-' where he has none."""

    points: str = ""
    """His fantasy points over the same span, in a points league; empty in a category one."""


POINTS_SCORING = frozenset({"headpoint", "point"})

INJURED = frozenset({"IL", "IL+"})
"""Roster slots that hold an injured player outside the active roster."""

UNSTARTED = INJURED | {"BN"}
"""Roster slots whose players score nothing: the bench and the injured ones."""
"""Yahoo's scoring types for a league scored in fantasy points: head-to-head, or over the season."""


@dataclass(frozen=True)
class MatchupSide:
    """One team's side of a head-to-head week."""

    team_key: str
    name: str
    points: str
    """Yahoo's score for the side, as it prints it: categories won in a category league, fantasy points in a points one."""

    stats: dict[str, str]
    """Yahoo stat id -> the side's value, as Yahoo prints it."""

    projected: str = ""
    """Yahoo's projected final score, as it prints it; empty where it gives none, as in a category league."""


@dataclass(frozen=True)
class YahooLeague:
    """One league the login plays in."""

    league_key: str
    """'466.l.123': the game, then the league. Every request about the league names it."""

    name: str
    league_type: str = ""
    current_week: int | None = None
    """None between seasons, when there is no week to read."""

    start_week: int | None = None
    end_week: int | None = None
    """The season's first and last matchup weeks, playoffs included; None where Yahoo sent neither."""

    scoring_type: str = ""
    """How Yahoo scores the league: 'head' or 'headone' by categories, 'headpoint' by fantasy points,
    'roto' by season-long category ranks."""

    @property
    def by_points(self) -> bool:
        """Whether a week is won on fantasy points, summed from the league's weights, rather than on categories."""
        return self.scoring_type in POINTS_SCORING

    @property
    def first_week(self) -> int:
        """The season's first matchup week."""
        return self.start_week or 1

    def last_week(self, current: int) -> int:
        """The season's last matchup week, and never before `current`, the week being played."""
        return max(self.end_week or current, current)


@dataclass(frozen=True)
class YahooPlayer:
    player_key: str
    name: str
    position: str
    """Every position the player is eligible at, as Yahoo prints it: 'PF,C'."""

    team: str
    """The NBA team's abbreviation."""

    status: str = ""
    """'O', 'GTD', 'INJ'; empty for a player with nothing reported."""

    injury_note: str = ""
    slot: str = ""
    """Where their manager has them this week: 'PG', 'BN', 'IL'. Empty off a roster."""

    stats: dict[str, str] = field(default_factory=dict)
    """Yahoo stat id -> his line over `coverage`, as Yahoo prints it ('-' for no games); empty unless asked for."""

    points: str = ""
    """His fantasy points over `coverage`, in a points league, as Yahoo prints it; empty unless asked for."""

    coverage: str = ""
    """The span `stats` and `points` cover, as Yahoo names it: 'week' for a week played, an `Average` on the
    wire; empty where they carry nothing."""

    image_url: str = ""
    """His headshot on Yahoo's CDN, full size; empty where Yahoo sent none."""

    owner: str = ""
    """Whose roster he is on — a team's name, 'Free agent' or 'Waivers' — where his ownership was asked for;
    empty otherwise."""

    @property
    def line(self) -> YahooLine:
        return YahooLine(stats=self.stats, points=self.points)


@dataclass(frozen=True)
class TeamStanding:
    rank: int
    wins: int
    losses: int
    ties: int
    points_for: str
    """As Yahoo prints it; empty where it gives none."""

    points_against: str = ""
    playoff_seed: int = 0
    """Zero until the regular season has seeded the bracket."""

    @property
    def record(self) -> str:
        return record(self.wins, self.losses, self.ties)


@dataclass(frozen=True)
class YahooTeam:
    team_key: str
    """'nba.l.123.t.4': the league, then the team."""

    name: str
    is_mine: bool = False
    """Owned by the login reading it."""

    adds_used: int = 0
    """Adds made this week, against the league's weekly limit."""

    standing: TeamStanding | None = None
    """None where Yahoo sent no standings with the team."""

    waiver_priority: int = 0
    """Place in the waiver order; zero where Yahoo sent none."""

    faab_balance: str = ""
    """Waiver budget left, as Yahoo prints it; empty in a league without FAAB."""


@dataclass(frozen=True)
class MovedPlayer:
    """One player a league transaction moved, and which way."""

    player_key: str
    name: str
    position: str
    team: str
    """His NBA club."""

    kind: str
    """What happened to him, in Yahoo's words: 'add', 'drop', 'trade'."""

    source: str = ""
    """Whose roster he left — a team's name — or where from: 'freeagents', 'waivers'."""

    destination: str = ""
    """Whose roster he joined — a team's name — or where to: 'waivers'."""


@dataclass(frozen=True)
class YahooTransaction:
    """One move the league made: an add, a drop, both at once, or a trade."""

    kind: str
    """In Yahoo's words: 'add', 'drop', 'add/drop', 'trade'."""

    timestamp: int
    """When it went through, in epoch seconds."""

    players: tuple[MovedPlayer, ...]
    bid: str = ""
    """The FAAB a waiver claim was won with, as Yahoo prints it; empty for none."""


@dataclass(frozen=True)
class StatCategory:
    """One category the league scores, as its settings name it."""

    stat_id: str
    name: str
    """What Yahoo displays it as: 'PTS', 'FG%'."""

    fewer_wins: bool = False
    """Won by the side with less of it: turnovers, in most leagues."""


@dataclass(frozen=True)
class LeagueSettings:
    """What a league's settings say about how it is scored, how often a team may add, and how its season ends.

    Whether a week is won on points or categories is the league's `scoring_type`,
    read once from the league list (`YahooLeague.by_points`), not from here.
    """

    categories: list[StatCategory] = field(default_factory=list)
    """The categories it scores, in the order its settings list them."""

    positions: list[str] = field(default_factory=list)
    """The lineup slots it has, as its settings list them: 'PG', 'G', 'Util', 'BN'."""

    weights: dict[str, float] = field(default_factory=dict)
    """Yahoo stat id -> fantasy points per unit, in a points league; empty in a category one."""

    max_weekly_adds: int | None = None
    """Adds a team may make in a week; None where the settings name no limit."""

    playoff_start_week: int = 0
    """Zero for a league with no playoffs."""

    playoff_teams: int = 0
    multiweek_final: bool = False

    weekly_lineups: bool = False
    """Whether a lineup is set once for the week rather than day by day: its starters play every game they have."""

    best_game: bool = False
    """Whether each player scores only his best game of the week — Yahoo's "High Score" points — not their sum."""

    trade_end: date | None = None
    """The last day a trade is accepted; None where the settings name none."""

    slots: dict[str, int] = field(default_factory=dict)
    """How many of each roster position a team holds, as the settings list them: 'PG': 1, 'BN': 3, 'IL': 2."""

    @property
    def starting(self) -> int:
        """Lineup slots that score: every position but the bench and the injured ones; nought where none are listed."""
        return sum(count for slot, count in self.slots.items() if slot not in UNSTARTED)

    @property
    def roster_size(self) -> int:
        """Players a team may hold outside its injured slots; nought where no positions are listed."""
        return sum(count for slot, count in self.slots.items() if slot not in INJURED)


@dataclass(frozen=True)
class Pairing:
    """One week's head-to-head as the scoreboard has it: its dates, and each side's categories."""

    start: date
    end: date
    mine: MatchupSide
    opponent: MatchupSide
    status: str = ""
    """'preevent', 'midevent' or 'postevent': not started, being played, or settled."""

    winner: str = ""
    """The winning team's key once settled; empty before, and for a tie."""

    tied: bool = False
    tied_categories: int = 0
    """Categories neither side won."""

    playoffs: bool = False
    consolation: bool = False
    """A playoff-week game for a team out of the championship bracket."""

    @property
    def settled(self) -> bool:
        return self.status == "postevent"


@dataclass(frozen=True)
class Matchup:
    """This week's head-to-head, read once for its score, its categories and its dates."""

    start: date
    end: date
    mine: MatchupSide
    opponent: MatchupSide
    opponent_roster: list[YahooPlayer]
