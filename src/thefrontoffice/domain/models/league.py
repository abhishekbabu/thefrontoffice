"""The league's season: the schedule, standings, the week's matches and recent moves."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from thefrontoffice.domain.models.activity import ActivityRow
from thefrontoffice.domain.models.players import PlayerRef
from thefrontoffice.domain.models.values import Stat, Tone

Outcome = Literal["won", "lost", "drawn"]


def outcome(mine: float, theirs: float) -> Outcome:
    """How a played matchup ended for the side scoring `mine`."""
    return "won" if mine > theirs else "lost" if mine < theirs else "drawn"


def record(wins: int, losses: int, ties: int = 0) -> str:
    """A head-to-head season as it is said: '4-2', and '4-2-1' only where there was a tie."""
    base = f"{wins}-{losses}"
    return f"{base}-{ties}" if ties else base


class ScheduleRow(BaseModel):
    """One week of your own season, played or still to come."""

    label: str = Field(description="What the league calls the week: 'Week 3', 'GW 12'.")
    date: str = Field(default="", description="When it is played, in the reader's words: 'Sep 14', 'Sat 13 Sep'.")
    opponent: str = Field(default="", description="Who you play. Empty on a bye, which is not an opponent named 'bye'.")
    detail: str = Field(default="", description="Their record, or however the league identifies them.")
    result: str = Field(
        default="",
        description="The score once it is played, the score so far while it is, and nothing before that.",
    )
    outcome: Outcome | None = Field(
        default=None, description="How it ended, once it has; None before, and while it is being played."
    )
    is_current: bool = False
    """The week in progress, so a long table can say where you are in it."""
    marks: list[str] = Field(
        default_factory=list,
        description="What else falls in the week, in the league's words: 'Trade deadline'. Empty for most.",
    )
    playoffs: bool = False
    """A bracket week rather than the regular season, so the two can be read apart."""


class TeamRef(BaseModel):
    """One team in the league, addressable so its roster can be opened."""

    team_id: str = Field(description="Identifier this platform uses for a team, roster or entry.")
    name: str
    detail: str = Field(default="", description="Record, manager, or however the league identifies them.")
    url: str = Field(default="", description="This team on its own platform, where there is such a page.")
    is_mine: bool = False


class StandingRow(BaseModel):
    """One team in the league table."""

    rank: int
    name: str
    detail: str = Field(default="", description="Manager, or however the league identifies the entry.")
    record: str = Field(default="", description="In the league's own terms: '3-1', '2W 1D 1L'.")
    points: str = Field(default="", description="What the table is actually sorted on.")
    team_id: str = Field(
        default="",
        description="Addresses this team's roster. Empty where the platform cannot serve one.",
    )
    playoffs: str = Field(
        default="", description="Chance of a playoff place, formatted. Empty where the season is not simulated."
    )
    points_against: str = Field(default="", description="Points scored against, formatted; empty where none.")
    waiver_budget: str = Field(default="", description="Waiver budget left, formatted: '$73'. Empty where none.")
    waiver_order: str = Field(default="", description="Place in the waiver order: '3'. Empty where none.")
    is_mine: bool = False
    """Yours, so a fourteen-team table does not have to be read to find it."""


class Match(BaseModel):
    """One real-world game behind a fantasy week.

    Distinct from a fantasy fixture: this is two actual clubs, on a date, and
    it is what a projection is a projection *about*.
    """

    label: str = Field(default="", description="When it kicks off, already formatted.")
    home: str
    away: str
    detail: str = Field(default="", description="Difficulty, status, or whatever that competition reads off a fixture.")
    tone: Tone = "neutral"
    home_score: int | None = Field(default=None, description="Points on the board once it has kicked off.")
    away_score: int | None = None
    kickoff: datetime | None = Field(
        default=None, description="When it starts, in UTC, for the page to show in the viewer's own zone."
    )
    yours: list[PlayerRef] = Field(
        default_factory=list, description="Your players in this game, starters first. Empty where you have none."
    )
    theirs: list[PlayerRef] = Field(
        default_factory=list, description="Your opponent's players in this game, starters first; empty where none."
    )


class Slate(BaseModel):
    """The real games one fantasy week is made of, and the clubs with none in it."""

    games: list[Match] = Field(default_factory=list, description="In kickoff order.")
    byes: list[str] = Field(
        default_factory=list,
        description="Clubs with no game that week, alphabetical; empty where every club plays, or none has played yet.",
    )
    note: str = Field(
        default="",
        description="One line on the slate as a whole, where it is not to be read as complete; empty for most.",
    )


class LeagueSchedule(BaseModel):
    """The league beyond this week: where the season goes, and where you sit.

    Every section is optional because the platforms genuinely differ — a
    classic FPL league has a table and no head-to-head season, and FPL has no
    transaction feed at all. An empty section renders as nothing rather than as
    an empty promise.
    """

    headline: list[Stat] = Field(
        default_factory=list, description="Your season in figures: record, place, points, playoff chance."
    )
    season: list[ScheduleRow] = Field(default_factory=list)
    standings: list[StandingRow] = Field(default_factory=list)
    matches: list[Match] = Field(default_factory=list)
    activity: list[ActivityRow] = Field(default_factory=list)
