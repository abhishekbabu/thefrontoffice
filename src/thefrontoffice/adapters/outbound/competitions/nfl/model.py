"""Fantasy football in its own terms: what the NFL's rules read, whatever platform the league is on.

The registry is keyed by competition and platform because one competition can
run on several. The rules here — the lineup solve, the to-do list, the
forecast's ranges, the weeks ahead, the trade search — are the competition's,
and they describe what they need rather than naming a platform's types: a
projection, a team, the league's rules, a real game. Sleeper's own types
already have these shapes, so its client satisfies `NFLSource` as it stands;
a second platform's would, by the same members, with no rule rewritten.

Structural on purpose: a Protocol states what is read, and anything with
those members is one. The few things the rules make for themselves — a
projection for a player with none, or one whose designation a later report
changed, a game whose status the scoreboard corrected — are concrete here,
as the NFL's own.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

Scoring = Literal["pts_ppr", "pts_half_ppr", "pts_std"]
"""How a league scores a reception: full, half, or not at all."""


class PlayerInfo(TypedDict, total=False):
    """What the rules read about a player from the platform's catalog."""

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


class Projection(Protocol):
    """One player's projected week."""

    @property
    def player_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def position(self) -> str: ...
    @property
    def team(self) -> str: ...
    @property
    def opponent(self) -> str:
        """Who his club plays this week; empty where it has no game, or he has no projection."""
        ...

    @property
    def points(self) -> float: ...
    @property
    def injury_status(self) -> str: ...
    @property
    def stats(self) -> Mapping[str, float]:
        """The projection broken out — passing yards, receptions, targets."""
        ...

    @property
    def is_questionable(self) -> bool: ...


@dataclass(frozen=True)
class Unprojected:
    """A player with no projection this week — on bye, or ruled out — kept at nought rather than dropped.

    The one projection the rules make for themselves: the report must see a
    starter who will not score, and a list without him cannot show him.
    """

    player_id: str
    name: str
    position: str
    team: str
    injury_status: str = ""
    opponent: str = ""
    points: float = 0.0
    stats: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_questionable(self) -> bool:
        return listed(self.injury_status)


@dataclass(frozen=True)
class Reported:
    """A projection under the designation the latest injury report gives him, rather than the one it was published with."""

    player_id: str
    name: str
    position: str
    team: str
    opponent: str
    points: float
    injury_status: str
    stats: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def of(cls, projection: Projection, injury_status: str) -> Reported:
        return cls(
            player_id=projection.player_id,
            name=projection.name,
            position=projection.position,
            team=projection.team,
            opponent=projection.opponent,
            points=projection.points,
            injury_status=injury_status,
            stats=projection.stats,
        )

    @property
    def is_questionable(self) -> bool:
        return listed(self.injury_status)


def listed(injury_status: str) -> bool:
    """Whether a designation is anything at all: a player cleared to play carries none, or Active."""
    return bool(injury_status) and injury_status.upper() != "ACTIVE"


class Team(Protocol):
    """One team in the league: who it holds, who it starts, and its record."""

    @property
    def roster_id(self) -> int: ...
    @property
    def owner_id(self) -> str: ...
    @property
    def player_ids(self) -> Sequence[str]: ...
    @property
    def starter_ids(self) -> Sequence[str]:
        """Positionally aligned with the league's starting slots."""
        ...

    @property
    def reserve_ids(self) -> Sequence[str]:
        """Injured-reserve and taxi slots: on the roster, not taking a spot on it."""
        ...

    @property
    def wins(self) -> int: ...
    @property
    def losses(self) -> int: ...
    @property
    def ties(self) -> int: ...
    @property
    def points_for(self) -> float: ...
    @property
    def record(self) -> str: ...


class LeagueRules(Protocol):
    """The league itself: its size, how it scores, its lineup, and its season's shape."""

    @property
    def league_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def total_rosters(self) -> int: ...
    @property
    def scoring_format(self) -> Scoring: ...
    @property
    def trade_deadline(self) -> int:
        """The last week trades are accepted; zero where the league set none."""
        ...

    @property
    def playoff_teams(self) -> int: ...
    @property
    def playoff_week_start(self) -> int: ...
    @property
    def roster_spots(self) -> int:
        """Players the roster holds outside its reserve and taxi slots."""
        ...

    @property
    def starting_slots(self) -> list[str]:
        """The lineup slots that score, in the league's order."""
        ...


class Game(Protocol):
    """One real NFL game."""

    @property
    def week(self) -> int: ...
    @property
    def date(self) -> str:
        """ISO date: the day, not the kickoff."""
        ...

    @property
    def home(self) -> str: ...
    @property
    def away(self) -> str: ...
    @property
    def status(self) -> str:
        """`pre_game`, `in_game` or `complete`; empty where the platform says nothing."""
        ...


@dataclass(frozen=True)
class GameNow:
    """A game with its status as the live scoreboard has it, rather than as the season's file did this morning."""

    week: int
    date: str
    home: str
    away: str
    status: str = ""

    @classmethod
    def of(cls, game: Game, status: str) -> GameNow:
        return cls(week=game.week, date=game.date, home=game.home, away=game.away, status=status)


class GameLine(Protocol):
    """One player's line from one game: what he scored, and the usage behind it."""

    @property
    def player_id(self) -> str: ...
    @property
    def week(self) -> int: ...
    @property
    def team(self) -> str: ...
    @property
    def opponent(self) -> str: ...
    @property
    def position(self) -> str: ...
    @property
    def stats(self) -> Mapping[str, float]: ...


class SeasonTotals(Protocol):
    """What a player did over a season."""

    @property
    def games(self) -> int: ...
    @property
    def position_rank(self) -> int: ...
    @property
    def splits(self) -> Mapping[str, float]: ...
    def scored(self, scoring: Scoring) -> float: ...
    def per_game(self, scoring: Scoring) -> float: ...


class LeagueMove(Protocol):
    """One completed transaction: who, which kind, and the players it moved."""

    @property
    def kind(self) -> str: ...
    @property
    def roster_ids(self) -> Sequence[int]: ...
    @property
    def adds(self) -> Mapping[str, int]: ...
    @property
    def drops(self) -> Mapping[str, int]: ...
    @property
    def when(self) -> int:
        """Epoch milliseconds."""
        ...


class Phase(Protocol):
    """Where the NFL season is."""

    @property
    def week(self) -> int: ...
    @property
    def season(self) -> str: ...
    @property
    def is_regular_season(self) -> bool: ...


class Trending(Protocol):
    """A player being added or dropped across the platform."""

    @property
    def player_id(self) -> str: ...
    @property
    def count(self) -> int: ...


class NFLSource(Protocol):
    """Every read the NFL's rules make of the league's platform, and nothing else.

    Matchup entries stay the platform's own rows — a team's id, its pairing,
    its points, its starters — read by key where they are read.
    """

    def get_league_users(self, league_id: str) -> dict[str, str]:
        """Each owner's display name, by owner id."""
        ...

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]: ...

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> dict[int, list[dict[str, Any]]]: ...

    def get_nfl_game_lines(self, season: str, weeks: list[int]) -> Sequence[GameLine]: ...

    def get_nfl_state(self) -> Phase: ...

    def get_players(self, sport: str = "nfl") -> Mapping[str, PlayerInfo]: ...

    def get_projections(self, season: str, week: int, scoring: Scoring) -> Mapping[str, Projection]: ...

    def get_rosters(self, league_id: str) -> Sequence[Team]: ...

    def get_season_schedule(self, season: str, sport: str = "nfl") -> Sequence[Game]: ...

    def get_season_stats(self, season: str, sport: str = "nfl") -> Mapping[str, SeasonTotals]: ...

    def get_state(self, sport: str = "nfl") -> Phase: ...

    def get_transactions(self, league_id: str, week: int) -> Sequence[LeagueMove]: ...

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> Sequence[Trending]: ...
