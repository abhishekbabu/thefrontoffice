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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupChange, LineupSlot
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.domain.errors import SleeperAPIError

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

    league: SleeperLeague
    roster: SleeperRoster
    week: int
    season: str
    projections: dict[str, WeeklyProjection]
    players: dict[str, PlayerMeta]
    projected: list[WeeklyProjection]
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
        return datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError, TypeError:
        return None


def day(iso: str) -> str:
    """One date, as a person reads it: 'Sun 13 Sep'."""
    parsed = parse_date(iso)
    return weekday_day_month(parsed) if parsed else ""


def week_dates(games: list[ScheduledGame]) -> str:
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


def games_by_week(client: SleeperClient, season: str) -> dict[int, list[ScheduledGame]]:
    """The season schedule bucketed by week, or nothing if it will not load.

    Dates are enrichment: a week without them is still a week.
    """
    try:
        games = client.get_season_schedule(season)
    except SleeperAPIError as e:
        logger.warning(f"Continuing without schedule dates: {e}")
        return {}
    by_week: dict[int, list[ScheduledGame]] = {}
    for game in games:
        by_week.setdefault(game.week, []).append(game)
    return by_week


# ── projections ─────────────────────────────────────────────────────────


def zero_projection(player_id: str, meta: PlayerMeta) -> WeeklyProjection:
    """A player with no projection this week: a bye, or inactive."""
    return WeeklyProjection(
        player_id=player_id,
        name=str(meta.get("name") or player_id),
        position=str(meta.get("position") or ""),
        team=str(meta.get("team") or "FA"),
        opponent="",
        points=0.0,
        injury_status=str(meta.get("injury_status") or ""),
    )


def projection_for(
    player_id: str, projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
) -> WeeklyProjection | None:
    """A player's projection, falling back to a zero-point entry.

    A rostered player with no projection is usually on a bye or inactive —
    which is exactly the case the report must see, so they are kept at zero
    rather than dropped from the projected.
    """
    if player_id in projections:
        return projections[player_id]
    meta = players.get(player_id)
    return zero_projection(player_id, meta) if meta else None
