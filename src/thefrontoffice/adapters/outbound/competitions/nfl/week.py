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
from typing import Any

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupChange, LineupSlot, optimal_lineup
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    GameNow,
    LeagueRules,
    NFLSource,
    PlayerInfo,
    Projection,
    Team,
    Unprojected,
)
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import ScoreboardGame
from thefrontoffice.domain.errors import PlatformError

logger = logging.getLogger(__name__)

SCORING_LABELS = {
    "pts_ppr": "Full PPR (1 point per reception)",
    "pts_half_ppr": "Half PPR (0.5 per reception)",
    "pts_std": "Standard (no point per reception)",
}


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

    @property
    def starter_ids(self) -> set[str]:
        return {slot.player.player_id for slot in self.lineup if slot.player}


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


def games_by_week(client: NFLSource, season: str) -> dict[int, list[Game]]:
    """The season schedule bucketed by week, or nothing if it will not load.

    Dates are enrichment: a week without them is still a week.
    """
    try:
        games = client.get_season_schedule(season)
    except PlatformError as e:
        logger.warning(f"Continuing without schedule dates: {e}")
        return {}
    by_week: dict[int, list[Game]] = {}
    for game in games:
        by_week.setdefault(game.week, []).append(game)
    return by_week


# ── projections ─────────────────────────────────────────────────────────


def zero_projection(player_id: str, meta: PlayerInfo) -> Projection:
    """A player with no projection this week: a bye, or inactive."""
    return Unprojected(
        player_id=player_id,
        name=str(meta.get("name") or player_id),
        position=str(meta.get("position") or ""),
        team=str(meta.get("team") or "FA"),
        injury_status=str(meta.get("injury_status") or ""),
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
    players = [p for p in (projection_for(pid, projections, state.players) for pid in player_ids) if p]
    return optimal_lineup(state.league.starting_slots, players)


def opponent_entry(state: Week, matchups: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The other side of your matchup this week, as Sleeper lists it; None on a bye or an unpaired week."""
    mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
    if not mine or mine.get("matchup_id") is None:
        return None
    return next(
        (
            m
            for m in matchups
            if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != state.roster.roster_id
        ),
        None,
    )


# ── the week as it is being played ──────────────────────────────────────

SCOREBOARD_STATUS = {"pre": "pre_game", "in": "in_game", "post": "complete"}
"""ESPN's game states in Sleeper's words, which is what the rest of the week reads."""


class Scoreboard:
    """Which games have kicked off, how far they are, and what has been scored: the week while it is played.

    Sleeper's season schedule says which games have started, but it is a
    season-long file cached for hours, and it carries no clock. ESPN's
    scoreboard is a minute old at most and says where each game is. Read once
    per week per request, and shared by everything that asks.
    """

    def __init__(self, client: NFLSource, espn: ESPNSource):
        self.client = client
        self.espn = espn
        self._boards: dict[int, dict[str, ScoreboardGame]] = {}

    def games(self, state: Week) -> dict[int, list[Game]]:
        """The season's games, with this week's status read off the live scoreboard where it answers."""
        games = games_by_week(self.client, state.season)
        board = self.board(state)
        if board and state.week in games:
            games[state.week] = [
                GameNow.of(game, SCOREBOARD_STATUS.get(board[game.home].state, game.status))
                if game.home in board
                else game
                for game in games[state.week]
            ]
        return games

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
                for game in games_by_week(self.client, state.season).get(state.week, [])
                if (pair := (espn_club(game.home), espn_club(game.away))) in by_pair
                for club in (game.home, game.away)
            }
        return self._boards[state.week]

    def live(self, state: Week, league_id: str) -> Live:
        """What has actually been scored, whose clubs have kicked off, and where their games are."""
        started = {
            club
            for game in self.games(state).get(state.week, [])
            if game.status and game.status != "pre_game"
            for club in (game.home, game.away)
        }
        clock = {club: game.label for club, game in self.board(state).items() if game.state == "in" and game.label}
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except PlatformError as e:
            logger.warning(f"Continuing without live scores: {e}")
            return Live(started=started, points={}, clock=clock)

        points: dict[str, float] = {}
        for entry in matchups:
            for player_id, scored in (entry.get("players_points") or {}).items():
                points[str(player_id)] = float(scored or 0)
        return Live(started=started, points=points, clock=clock)
