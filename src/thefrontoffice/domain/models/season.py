"""What simulating the rest of a season takes and gives: records in, playoff odds, outlooks and trades out."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from thefrontoffice.domain.models.values import Stat


@dataclass(frozen=True)
class TeamRecord:
    """One team's regular season so far: what is already banked."""

    team_id: str
    name: str
    wins: int
    losses: int
    ties: int
    points_for: float


@dataclass(frozen=True)
class TeamWeek:
    """How one team is expected to score in one week still to come."""

    team_id: str
    week: int
    mean: float
    spread: float
    """Standard deviation of a week's score around `mean`."""


@dataclass(frozen=True)
class Fixture:
    """One head-to-head matchup still to be played."""

    week: int
    home: str
    away: str
    chances: tuple[float, float] | None = None
    """The home side's chance of winning it and the away side's, a draw the rest, where a week is not
    two scores compared — one won on the most categories. None where the teams' `TeamWeek` scores decide it."""


@dataclass(frozen=True)
class SeasonInput:
    """The rest of a regular season, ready to simulate: records, fixtures, and each team's weekly scoring.

    Seeded by record, then points for — the tiebreak a league uses unless it says otherwise.
    """

    teams: tuple[TeamRecord, ...]
    fixtures: tuple[Fixture, ...]
    scoring: tuple[TeamWeek, ...]
    spots: int
    mine: str
    week: int
    """The week in progress: the one whose result the odds are split on."""
    strength_error: float = 0.0
    """How far a team's real strength may sit from its means, in points: one offset per
    team per simulated season, so a team that is better than it looks stays better all
    season rather than winning a week and losing the next."""
    seed: int = 0


class TeamOdds(BaseModel):
    """One team's chance of reaching the playoffs."""

    team_id: str
    name: str
    playoffs: float


class PlayoffOdds(BaseModel):
    """The rest of the regular season played many times over."""

    spots: int
    teams: list[TeamOdds] = Field(default_factory=list)
    playoffs: float = Field(description="Your chance of a playoff place.")
    with_win: float | None = Field(default=None, description="Your chance if you win this week; None on a bye.")
    with_loss: float | None = Field(default=None, description="Your chance if you lose this week; None on a bye.")
    simulations: int


class WeekAhead(BaseModel):
    """One coming week for your roster: what its best lineup projects, and what to do if that is short.

    Byes and injuries are known weeks out, and a week where several land at
    once is a loss that can be seen coming: this is where it is seen, while
    there is a waiver run or two to fix it.
    """

    week: int
    points: float = Field(description="Your best legal lineup's projection that week.")
    missing: list[str] = Field(
        default_factory=list, description="Regular starters who will not play that week, and why: 'Josh Allen (bye)'."
    )
    short_by: float = Field(description="How far the week falls below the usual one; negative where it is above.")
    short: bool = Field(description="Whether the week falls far enough below the usual to act on.")
    light: list[str] = Field(
        default_factory=list,
        description="Regulars with few games that week, where a week counts games: 'Jalen Brunson (2 games)'.",
    )
    heavy: bool = Field(
        default=False,
        description="Whether most clubs play four or more games that week: a stream brings more of them.",
    )
    provisional: bool = Field(
        default=False,
        description="Whether the league has days of that week still to schedule, so its games are a floor.",
    )
    fix: str = Field(default="", description="The pickup that closes most of the gap, and who to drop for him.")
    gain: float = Field(default=0.0, description="What that pickup adds to the week, in its competition's measure.")


class Opposition(BaseModel):
    """One match a club plays in a week to come, as a fixture grid cell reads it."""

    opponent: str = Field(description="The club faced, as a table spells it: 'ARS'.")
    home: bool
    difficulty: int = Field(description="The league's own 1-5 rating of the match for the club facing it; 5 hardest.")


class FixtureWeek(BaseModel):
    """One week of a player's run: no match is a blank, two a double."""

    week: int
    games: list[Opposition] = Field(default_factory=list)


class FixtureRun(BaseModel):
    """One player's matches over the weeks ahead, with why the row is worth a look."""

    player_id: str
    player: str
    detail: str = Field(default="", description="Position and club: 'MID · LIV'.")
    weeks: list[FixtureWeek] = Field(description="One per week the grid covers, in order, a blank included.")
    flags: list[str] = Field(
        default_factory=list,
        description="What earns the row its place, in words: 'blank GW14', 'double GW15', '3 hard', 'injured'.",
    )


class Outlook(BaseModel):
    """The next few weeks for your roster, soonest first, each measured against the same usual week."""

    usual: float | None = Field(
        default=None,
        description="What your best lineup projects in a typical one of these weeks. None once none are left.",
    )
    measure: Literal["proj", "games"] = Field(
        default="proj",
        description=(
            "What a week's `points` count: projected points, or the games the daily lineups can start "
            "where a week is won on how many games are played."
        ),
    )
    weeks: list[WeekAhead] = Field(default_factory=list)
    run_weeks: list[int] = Field(
        default_factory=list,
        description=(
            "The weeks a fixture grid covers, soonest first — where the competition projects its weeks "
            "ahead as fixtures rather than as lineups. Empty otherwise."
        ),
    )
    runs: list[FixtureRun] = Field(
        default_factory=list,
        description="The players whose run has something to act on — a blank, a double, a hard stretch, a doubt.",
    )
    clear: int = Field(default=0, description="Players on the roster whose run has nothing to flag, left off `runs`.")
    warnings: list[Stat] = Field(
        default_factory=list,
        description="Each week a blank or a double lands on the roster, naming who: 'GW14' — '3 blank: Saka, Rice, Raya'.",
    )


@dataclass(frozen=True)
class TradeOption:
    """One trade worth simulating: who moves, and how both teams score once it has.

    The provider proposes it, because which trades make sense is a question of
    lineups and positions; the season engine prices it, by playing the season
    out with these rows in place of the two teams' own.
    """

    team_id: str
    """The other side of the trade."""
    giving: tuple[str, ...]
    receiving: tuple[str, ...]
    """Who moves each way, by name."""
    points: float
    """Your starters' projected points a week, with the trade less without it."""
    their_points: float
    """The same for theirs, across every week left: what a manager still chasing a place weighs."""
    scoring: tuple[TeamWeek, ...]
    """Both teams' scoring in each week the trade changes, replacing their rows in the season."""
    playoff_points: float | None = None
    """Your starters' projected points a playoff week, with the trade less without it; None where
    the playoff weeks are not projected yet."""
    pickup: str = ""
    """The free agent who fills the roster spot a two-for-one frees, where one helps."""
    form: tuple[Stat, ...] = ()
    """The players in it whose own games move their price off their projection, and why."""
    fixtures: tuple[Fixture, ...] = ()
    """Both teams' fixtures in each week the trade changes, replacing theirs in the season, where a
    week is decided on `Fixture.chances` rather than on scores."""
    giving_ids: tuple[str, ...] = ()
    receiving_ids: tuple[str, ...] = ()
    """The same players by id, in the same order, for opening them."""


TradeMeasure = Literal["points", "categories"]
"""What a trade's figures count: fantasy points, or the categories a side expects to win."""


@dataclass(frozen=True)
class TradeMarket:
    """The rest of the season, and the trades worth playing it out with."""

    season: SeasonInput
    options: tuple[TradeOption, ...]
    regular_weeks: int
    """The regular-season weeks a trade changes: those after this one, whose lineups are not yet set."""
    playoff_weeks: int
    """The playoff weeks projected, which a trade's `playoff_points` is a week of."""
    measure: TradeMeasure = "points"
    deadline: date | None = None
    """The last day the league takes a trade, where its settings name one."""
    least_their_gain: float | None = None
    """What a week the other side's lineup must gain for him to say yes, in `measure`; None for football's half-point."""
    least_total_gain: float | None = None
    """The least over the rest of the season a trade must add for you, in `measure`; None for football's three points."""


class TradeIdea(BaseModel):
    """A trade worth offering, priced in what it does to the playoff race and to the playoffs themselves."""

    team_id: str
    team: str = Field(description="The manager to offer it to.")
    giving: list[str]
    receiving: list[str]
    giving_ids: list[str] = Field(
        default_factory=list, description="Who you give, by player id, in the order of `giving`: to open them."
    )
    receiving_ids: list[str] = Field(
        default_factory=list, description="Who you get, by player id, in the order of `receiving`."
    )
    playoffs: float = Field(description="Your chance of a playoff place with the trade made.")
    playoffs_change: float = Field(description="That chance less your chance without it.")
    their_playoffs_change: float = Field(description="The same for the other side: what you would hand a rival.")
    points: float = Field(
        description="Your starters' projected points a week over the regular season left, with the trade less without "
        "it — or, where `Trades.measure` is categories, the categories you expect to win a week."
    )
    their_points: float = Field(
        description="The same for theirs over every week left, which is the case for them saying yes."
    )
    playoff_points: float | None = Field(
        default=None, description="Your starters' projected points a playoff week, with the trade less without it."
    )
    total: float = Field(
        description="Your starters' expected points over the rest of the season, with the trade less without it: "
        "every regular-season week left, and each playoff week weighed by your chance of being in it."
    )
    their_playoffs: float = Field(
        default=0.0,
        description="Their chance of a playoff place before the trade: out of it, they have only worth to weigh.",
    )
    pickup: str = Field(
        default="",
        description="The free agent added to the roster spot a two-for-one frees, where not the list's shared one.",
    )
    form: list[Stat] = Field(
        default_factory=list,
        description="The players in it whose own games move their price off their projection, and why, "
        "each said on the first trade he is in.",
    )


TradeRank = Literal["playoffs_change", "total"]
"""Which of a `TradeIdea`'s figures for you a list of them is ordered by."""


class Trades(BaseModel):
    """The trades worth offering, best first, with what most of them share said once rather than on each."""

    ideas: list[TradeIdea] = Field(default_factory=list)
    measure: TradeMeasure = Field(
        default="points",
        description="What each idea's figures for a lineup count: fantasy points, or expected categories won.",
    )
    deadline: date | None = Field(default=None, description="The last day the league takes a trade, where known.")
    ranked_by: TradeRank = Field(
        default="playoffs_change",
        description="The figure on each idea the list is ordered by: your playoff chance, or once that is "
        "safe, your starters' expected points over the rest of the season.",
    )
    pickup: str = Field(
        default="",
        description="The free agent most of the two-for-ones would add to the spot they free; an idea "
        "names its own pickup only where it is someone else.",
    )
