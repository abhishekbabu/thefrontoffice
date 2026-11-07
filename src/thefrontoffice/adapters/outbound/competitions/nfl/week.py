"""One football week, gathered once and read by everything that describes it.

The week is the unit this sport is organised around: the lineup view, the
league view and the prompt all ask about the same seven days, and all three
would otherwise fetch the same projections and re-run the same lineup solve.
Gathering it once means they cannot disagree about the totals by a rounding.

`Live` sits beside it because "what has been scored" and "what is projected"
are the same question asked at two different times, and a row has to know
which of the two it is showing.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cached_property

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupChange, LineupSlot, optimal_lineup
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    GameNow,
    LeagueRules,
    Matchup,
    NFLSource,
    PlayerInfo,
    Projection,
    Team,
    Unprojected,
    by_club,
    kicked_off,
)
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import ScoreboardGame
from thefrontoffice.domain.errors import PlatformError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Live:
    """The week as it has actually gone, so far.

    Zero points is ambiguous on its own — a receiver who dropped everything and
    a receiver whose game is on Monday both sit at nought — so the real-world
    schedule decides which of the two a row is showing.
    """

    started: set[str]
    """Clubs whose real-world game has kicked off."""

    points: dict[str, float]
    """What each player has scored, keyed by Sleeper's player_id."""

    clock: dict[str, str] = field(default_factory=dict)
    """Where each club's game is while it is on — 'Q3 13:02', 'Halftime' — by Sleeper's abbreviation."""

    def scored(self, player_id: str, team: str) -> float | None:
        """Points where that club's game has started, and nothing before it."""
        if not self.under_way or team not in self.started:
            return None
        return self.points.get(player_id)

    @property
    def under_way(self) -> bool:
        """Both halves are required. Kickoffs with no scoreboard behind them
        would render every row as nought — a whole team that blanked, rather
        than a request that failed."""
        return bool(self.started) and bool(self.points)


@dataclass(frozen=True)
class Week:
    """One week's state, gathered once and read by every view of it."""

    league: LeagueRules
    roster: Team
    week: int
    season: str
    projections: Mapping[str, Projection]
    players: Mapping[str, PlayerInfo]
    projected: Sequence[Projection]
    lineup: list[LineupSlot]
    best: list[LineupSlot]
    changes: list[LineupChange]
    current_points: float
    best_points: float
    on_bench: float

    rosters: Sequence[Team] = ()
    """Every team in the league, yours among them, each starting the lineup it set for this week."""

    names: Mapping[str, str] = field(default_factory=dict)
    """Each manager's name, by owner id."""

    matchups: Sequence[Matchup] = ()
    """This week's head-to-heads, one entry per team. Empty wherever they would not load."""

    is_regular_season: bool = False
    """Whether the season has actually begun. In preseason every season total
    is a nought that has not been earned yet."""

    evidence: Evidence = field(default_factory=Evidence)
    """Each player's role and each defense's record, from games already played.
    Empty in week 1, and wherever the stat lines would not load."""

    news: PlayerNews = field(default_factory=PlayerNews)
    """Recent articles about each player. Empty wherever the feeds would not load."""

    @property
    def scheduled(self) -> bool:
        """Whether the league has published fixtures at all.

        Before the season opens Sleeper publishes none, and flagging every
        player for having no game turns the page amber over a date rather than
        a decision. It only means something once others do have one.
        """
        return any(p.opponent for p in self.projected)

    @cached_property
    def starter_ids(self) -> set[str]:
        """Who your lineup starts, as the solve read it: an ineligible or unknown player fills no slot."""
        return {slot.player.player_id for slot in self.lineup if slot.player}

    @property
    def sitting(self) -> list[Projection]:
        """Everyone your lineup does not start, reserve and taxi slots included."""
        return [p for p in self.projected if p.player_id not in self.starter_ids]

    @property
    def bench(self) -> list[Projection]:
        """Who could come into the lineup: sitting, and not in an injured-reserve or taxi slot."""
        return [p for p in self.sitting if p.player_id not in self.roster.reserve_ids]

    @cached_property
    def owned(self) -> set[str]:
        """Every player on a roster in this league: who is not on the wire."""
        return {pid for team in self.rosters for pid in team.player_ids}

    @cached_property
    def matchup(self) -> tuple[Matchup, Matchup] | None:
        """Your side of this week's head-to-head and your opponent's; None on a bye or an unpaired week."""
        return opponent_of(self.matchups, self.roster.roster_id)

    @property
    def opponent(self) -> Team | None:
        """The team you play this week; None on a bye, an unpaired week, or matchups that would not load."""
        if self.matchup is None:
            return None
        return next((team for team in self.rosters if team.roster_id == self.matchup[1].roster_id), None)

    def team_name(self, team: Team) -> str:
        return team_name(self.names, team)


def team_name(names: Mapping[str, str], team: Team) -> str:
    """Who manages a team, by name; the team's own number where the league names nobody."""
    return names.get(team.owner_id, f"Roster {team.roster_id}")


def weeks_played(week: int, is_regular_season: bool) -> list[int]:
    """The weeks finished before this one: none until the regular season is under way.

    The current week is left out even when it is part played: a player whose
    game is on Monday has a line of noughts until then.
    """
    return list(range(1, week)) if is_regular_season else []


# ── who plays whom ──────────────────────────────────────────────────────


def pairings(matchups: Iterable[Matchup]) -> list[tuple[Matchup, Matchup]]:
    """A week's head-to-heads, each as its two sides, the lower roster id first.

    A team with nobody to play — a bye, or a pairing with one side missing — is in none.
    """
    paired: dict[int, list[Matchup]] = {}
    for entry in matchups:
        if entry.matchup_id is not None:
            paired.setdefault(entry.matchup_id, []).append(entry)
    return [
        (first, second)
        for first, second in (
            sorted(sides, key=lambda side: side.roster_id) for sides in paired.values() if len(sides) == 2
        )
    ]


def opponent_of(matchups: Iterable[Matchup], roster_id: int) -> tuple[Matchup, Matchup] | None:
    """A team's side of the week and its opponent's; None where it plays nobody."""
    for first, second in pairings(matchups):
        if first.roster_id == roster_id:
            return first, second
        if second.roster_id == roster_id:
            return second, first
    return None


# ── when the week is played ─────────────────────────────────────────────


def parse_date(iso: str) -> date | None:
    """Sleeper publishes a day, not an instant, so this is a label not a time."""
    try:
        return date.fromisoformat(iso[:10])
    except ValueError, TypeError:
        return None


def day(iso: str) -> str:
    """One date, as a person reads it: 'Sun 13 Sep'."""
    parsed = parse_date(iso)
    return weekday_day_month(parsed) if parsed else ""


def week_dates(games: Sequence[Game]) -> str:
    """The span a fantasy week actually covers.

    An NFL week runs Thursday to Monday, so one date would be wrong for most
    of it and a range is what somebody checks against their own calendar.
    """
    days = sorted({d for d in (parse_date(g.date) for g in games) if d})
    if not days:
        return ""
    if days[0] == days[-1]:
        return day_month(days[0])
    if days[0].month == days[-1].month:
        return f"{days[0].day}-{day_month(days[-1])}"
    return f"{day_month(days[0])} - {day_month(days[-1])}"


def moment(epoch_ms: int) -> str:
    """Sleeper timestamps transactions in epoch milliseconds.

    Rendered in UTC rather than the machine's zone: it is a label on a list,
    and a league spans zones anyway.
    """
    if not epoch_ms:
        return ""
    return day_month(datetime.fromtimestamp(epoch_ms / 1000, tz=UTC))


# ── projections ─────────────────────────────────────────────────────────


def zero_projection(player_id: str, meta: PlayerInfo) -> Projection:
    """A player with no projection this week: a bye, or inactive."""
    return Unprojected(
        player_id=player_id,
        name=meta.name,
        position=meta.position,
        team=meta.team,
        injury_status=meta.injury_status,
    )


def counted(projection: Projection) -> Projection:
    """A projection as this week's lineup counts it: nought for a player ruled out, whatever is still published for him.

    Sleeper keeps projecting a player it has ruled out, so a lineup solved on
    its numbers starts him, and a header totalled on them counts points
    nobody will score — beside a to-do list telling you to bench him.
    """
    if not ruled_out(projection.injury_status) or not projection.points:
        return projection
    return Unprojected(
        player_id=projection.player_id,
        name=projection.name,
        position=projection.position,
        team=projection.team,
        injury_status=projection.injury_status,
        opponent=projection.opponent,
    )


def projection_for(
    player_id: str, projections: Mapping[str, Projection], players: Mapping[str, PlayerInfo]
) -> Projection | None:
    """A player's projection, falling back to a zero-point entry.

    A rostered player with no projection is usually on a bye or inactive —
    which is exactly the case the report must see, so they are kept at zero
    rather than dropped from the projected.
    """
    if player_id in projections:
        return projections[player_id]
    meta = players.get(player_id)
    return zero_projection(player_id, meta) if meta else None


def projections_for(
    player_ids: Iterable[str], projections: Mapping[str, Projection], players: Mapping[str, PlayerInfo]
) -> list[Projection]:
    """These players' projections, in their order; one nobody has heard of is left out."""
    return [p for p in (projection_for(pid, projections, players) for pid in player_ids) if p]


QUARTER = 15 * 60
"""Seconds in an NFL quarter; four of them make regulation."""

REGULATION = 4 * QUARTER


def left_in(game: ScoreboardGame) -> float:
    """How much of an NFL game is still to play, from 1 before kickoff to 0 at the end.

    Overtime is read as what is left of its own clock against a whole game,
    which is about right: a few minutes, and it may end at any snap.
    """
    if game.state == "pre":
        return 1.0
    if game.state == "post":
        return 0.0
    if game.period > 4:
        return min(1.0, game.clock / REGULATION)
    played = (max(game.period, 1) - 1) * QUARTER + (QUARTER - game.clock)
    return max(0.0, min(1.0, 1 - played / REGULATION))


def lineup_for(state: Week, player_ids: Iterable[str], projections: Mapping[str, Projection]) -> list[LineupSlot]:
    """The best legal lineup these players make, on these projections: this week's, or one still to come.

    The one place a week's lineup is solved from a set of player ids: the
    season simulation, the weeks ahead and the trade search all ask it, for
    weeks and rosters the week itself does not hold.
    """
    return optimal_lineup(state.league.starting_slots, projections_for(player_ids, projections, state.players))


# ── the week as it is being played ──────────────────────────────────────

SCOREBOARD_STATUS = {"pre": "pre_game", "in": "in_game", "post": "complete"}
"""ESPN's game states in Sleeper's words, which is what the rest of the week reads."""


class Scoreboard:
    """The season's real games, and this week's as they are played: which have kicked off, how far, what is scored.

    Sleeper's season schedule says which games have started, but it is a
    season-long file cached for hours, and it carries no clock. ESPN's
    scoreboard is a minute old at most and says where each game is. Each is
    read once per request, and shared by everything that asks.
    """

    def __init__(self, client: NFLSource, espn: ESPNSource):
        self.client = client
        self.espn = espn
        self._schedules: dict[str, dict[int, list[Game]]] = {}
        self._boards: dict[int, dict[str, ScoreboardGame]] = {}
        self._games: dict[tuple[str, int], dict[int, list[Game]]] = {}

    def schedule(self, season: str) -> Mapping[int, Sequence[Game]]:
        """The season's games bucketed by week, as the season's file has them; empty if it will not load.

        Dates are enrichment: a week without them is still a week.
        """
        if season not in self._schedules:
            try:
                games = self.client.get_nfl_schedule(season)
            except PlatformError as e:
                logger.warning(f"Continuing without schedule dates: {e}")
                games = []
            by_week: dict[int, list[Game]] = {}
            for game in games:
                by_week.setdefault(game.week, []).append(game)
            self._schedules[season] = by_week
        return self._schedules[season]

    def games(self, state: Week) -> Mapping[int, Sequence[Game]]:
        """The season's games, with this week's status read off the live scoreboard where it answers."""
        key = (state.season, state.week)
        if key not in self._games:
            games = {week: list(each) for week, each in self.schedule(state.season).items()}
            board = self.board(state)
            if board and state.week in games:
                games[state.week] = [
                    GameNow.of(game, SCOREBOARD_STATUS.get(board[game.home].state, game.status))
                    if game.home in board
                    else game
                    for game in games[state.week]
                ]
            self._games[key] = games
        return self._games[key]

    def started(self, state: Week) -> set[str]:
        """Clubs whose game this week has kicked off: their players are locked in or out."""
        return {
            club for club, game in by_club(self.games(state).get(state.week, [])).items() if kicked_off(game.status)
        }

    def board(self, state: Week) -> dict[str, ScoreboardGame]:
        """This week's games as they stand, keyed by each of the two clubs in Sleeper's abbreviations."""
        if state.week not in self._boards:
            try:
                board = self.espn.get_scoreboard(espn.NFL, state.season, state.week)
            except ESPNAPIError as e:
                # The schedule's own status is stale, not wrong about a game long finished.
                logger.warning(f"Continuing without the live scoreboard: {e}")
                board = []
            by_pair = {(game.home, game.away): game for game in board}
            self._boards[state.week] = {
                club: by_pair[pair]
                for game in self.schedule(state.season).get(state.week, [])
                if (pair := (espn_club(game.home), espn_club(game.away))) in by_pair
                for club in (game.home, game.away)
            }
        return self._boards[state.week]

    def live(self, state: Week) -> Live:
        """What has actually been scored, whose clubs have kicked off, and where their games are."""
        clock = {club: game.label for club, game in self.board(state).items() if game.state == "in" and game.label}
        points = {pid: scored for entry in state.matchups for pid, scored in entry.players_points.items()}
        return Live(started=self.started(state), points=points, clock=clock)
