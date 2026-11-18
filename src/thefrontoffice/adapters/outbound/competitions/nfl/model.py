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

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from thefrontoffice.domain.errors import FrontOfficeError

Scoring = Literal["pts_ppr", "pts_half_ppr", "pts_std"]
"""How a league scores a reception: full, half, or not at all."""


FREE_AGENT = "FA"
"""The club a player on no NFL roster is filed under, in a catalog entry and a projection alike — never empty.

The platform's client files him there, and cannot import this; the two are
kept equal by `test_model.py`."""


class PlayerInfo(Protocol):
    """What the rules read about a player from the platform's catalog: every field present, a number zero where unknown.

    Nothing here is optional, so a reader takes each as it stands rather than
    coercing a value that may be missing.
    """

    @property
    def player_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def position(self) -> str:
        """Empty where the catalog has none."""
        ...

    @property
    def team(self) -> str:
        """His club; `FREE_AGENT` where he has none."""
        ...

    @property
    def injury_status(self) -> str:
        """Empty for a player carrying no designation."""
        ...

    @property
    def depth_chart_order(self) -> int:
        """Zero where his club lists him nowhere."""
        ...

    @property
    def years_exp(self) -> int: ...
    @property
    def age(self) -> int: ...
    @property
    def college(self) -> str: ...
    @property
    def number(self) -> int: ...
    @property
    def injury_body_part(self) -> str: ...
    @property
    def injury_notes(self) -> str: ...


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
    def ir_ids(self) -> Sequence[str]:
        """The injured-reserve slots alone."""
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
    def points_against(self) -> float: ...
    @property
    def waiver_budget_used(self) -> int: ...
    @property
    def waiver_position(self) -> int:
        """Place in the waiver order; nought where the platform gives none."""
        ...

    @property
    def record(self) -> str: ...


def active(team: Team) -> list[str]:
    """Who takes a spot on the roster: everyone outside its injured-reserve and taxi slots."""
    return [pid for pid in team.player_ids if pid not in team.reserve_ids]


def open_spots(league: LeagueRules, team: Team) -> int:
    """Roster spots the team holds nobody in: the league's, less everyone outside reserve and taxi."""
    return max(0, league.roster_spots - len(active(team)))


def let_go(team: Team) -> list[str]:
    """Who the team started this week but no longer holds: dropped or traded once his game was played.

    The week's lineup keeps him and his points, so leaving him out would read
    as an empty slot in a week the team actually filled.
    """
    held = set(team.player_ids)
    return [pid for pid in team.starter_ids if pid and pid not in held]


def fielded(team: Team) -> list[str]:
    """Everyone who plays for the team this week: its roster, and the starters it has since let go."""
    return [*team.player_ids, *let_go(team)]


class LeagueRules(Protocol):
    """The league itself: its size, how it scores, its lineup, and its season's shape."""

    @property
    def league_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def season(self) -> str: ...
    @property
    def total_rosters(self) -> int: ...
    @property
    def scoring_format(self) -> Scoring: ...
    @property
    def scoring_rules(self) -> Mapping[str, float]:
        """Points per unit of each stat, as the league set them; every line is priced by them."""
        ...

    @property
    def trade_deadline(self) -> int:
        """The last week trades are accepted; zero where the league set none."""
        ...

    @property
    def playoff_teams(self) -> int: ...
    @property
    def playoff_week_start(self) -> int: ...
    @property
    def waiver_budget(self) -> int:
        """Each team's FAAB for the season; nought where the league uses none."""
        ...

    @property
    def draft_id(self) -> str:
        """The league's draft this season; empty where it has none."""
        ...

    @property
    def ir_allows(self) -> frozenset[str]:
        """The designations the injured-reserve slot takes, upper-cased."""
        ...

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


def by_club(games: Iterable[Game]) -> dict[str, Game]:
    """Each club's game, under either side's abbreviation; a club on bye is in none."""
    return {club: game for game in games for club in (game.home, game.away)}


COMPLETE = "complete"
"""A game's status once it is over."""


def kicked_off(status: str) -> bool:
    """Whether a game in this status has started: under way, or over. An unknown status is not started."""
    return bool(status) and status != "pre_game"


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

    @property
    def bid(self) -> int:
        """The waiver budget spent on it; nought for none."""
        ...

    @property
    def budget(self) -> Sequence[tuple[int, int, int]]:
        """Waiver budget a trade moved: (sender roster, receiver roster, amount)."""
        ...


class Pick(Protocol):
    """One pick of the league's draft."""

    @property
    def player_id(self) -> str: ...
    @property
    def roster_id(self) -> int: ...
    @property
    def round(self) -> int: ...
    @property
    def pick_no(self) -> int:
        """Overall, counted from 1."""
        ...


class Matchup(Protocol):
    """One team's side of a week's head-to-head: who it plays, what it has scored, and the lineup it set."""

    @property
    def roster_id(self) -> int: ...
    @property
    def matchup_id(self) -> int | None:
        """Shared by the two teams playing each other; None where the team plays nobody this week."""
        ...

    @property
    def points(self) -> float: ...
    @property
    def starters(self) -> Sequence[str]:
        """Positionally aligned with the league's starting slots; an empty slot is an empty string.

        The week's own lineup, which can be newer than the one its `Team` carries."""
        ...

    @property
    def players_points(self) -> Mapping[str, float]:
        """What each of the team's players has scored this week."""
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


class Weeks[V](Protocol):
    """What a read of several weeks found: each week that loaded, and why each that did not.

    A failed week is carried rather than left out, so no reader has to tell
    one from a week with nothing in it by its absence.
    """

    @property
    def values(self) -> Mapping[int, V]:
        """Each week that loaded."""
        ...

    @property
    def failures(self) -> Mapping[int, FrontOfficeError]:
        """Why each week that did not load did not."""
        ...

    def value(self, key: int) -> V:
        """One week, raising why it would not load where it did not."""
        ...


class NFLSource(Protocol):
    """Every read the NFL's rules make of the league's platform, and nothing else."""

    def get_league_users(self, league_id: str) -> dict[str, str]:
        """Each owner's display name, by owner id."""
        ...

    def get_matchups(self, league_id: str, week: int) -> Sequence[Matchup]: ...

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> Weeks[Sequence[Matchup]]:
        """Each of `weeks`: its matchups, or why it would not load — where an empty one is a bye."""
        ...

    def get_nfl_game_lines(
        self,
        season: str,
        weeks: list[int],
        positions: Collection[str],
        scoring: Scoring,
        rules: Mapping[str, float],
    ) -> Weeks[Sequence[GameLine]]:
        """Every line from each game in `weeks` by a player at one of `positions`, by week.

        A week that would not load is a failure, not empty: no line in a week
        that did is a game missed.
        """
        ...

    def get_nfl_players(self) -> Mapping[str, PlayerInfo]: ...

    def get_nfl_schedule(self, season: str) -> Sequence[Game]: ...

    def get_nfl_state(self) -> Phase: ...

    def get_projections(
        self,
        season: str,
        week: int,
        scoring: Scoring,
        positions: Collection[str],
        rules: Mapping[str, float],
    ) -> Mapping[str, Projection]:
        """The week's projections for the players at `positions`, by player id."""
        ...

    def get_projections_bulk(
        self,
        season: str,
        weeks: list[int],
        scoring: Scoring,
        positions: Collection[str],
        rules: Mapping[str, float],
    ) -> Weeks[Mapping[str, Projection]]:
        """Each of `weeks`' projections as `get_projections` reads one, or why it would not load."""
        ...

    def get_rosters(self, league_id: str) -> Sequence[Team]: ...

    def get_season_stats(self, season: str, scoring: Scoring, rules: Mapping[str, float]) -> Mapping[str, SeasonTotals]:
        """A season's totals by player id, its points in `scoring` priced by the league's `rules`."""
        ...

    def get_transactions(self, league_id: str, week: int) -> Sequence[LeagueMove]: ...

    def get_transactions_bulk(self, league_id: str, weeks: list[int]) -> Weeks[Sequence[LeagueMove]]:
        """Each of `weeks`: its completed moves, or why it would not load."""
        ...

    def get_draft_picks(self, draft_id: str) -> Sequence[Pick]:
        """Every pick of a draft, in the order made; none for a draft not yet held."""
        ...

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> Sequence[Trending]: ...
