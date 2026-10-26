"""Competition-agnostic report types.

Competitions differ in almost every detail — categories versus points, adds
versus a transfer budget, head-to-head versus league rank — but a report has
the same shape in each: read the situation, propose a ranked set of moves,
summarize the plan. One renderer, one chat-seeding path and one UI serve them all.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

MoveAction = Literal[
    "ADD",  # claim from the waiver wire / free agency
    "DROP",  # cut without a paired add
    "START",  # move into the starting lineup
    "BENCH",  # move out of the starting lineup
    "TRANSFER",  # swap one player for another, paired with `replaces`
    "CAPTAIN",  # nominate as captain
    "MONITOR",  # no action possible now; watch for later
]


class Move(BaseModel):
    """One recommended action on one player."""

    action: MoveAction = Field(description="What to do with this player.")
    player: str = Field(description="Full player name as the platform spells it.")
    position: str = Field(description="Position or eligible slots, e.g. 'RB' or 'PG,SG'.")
    team: str = Field(description="Real-world team abbreviation, e.g. 'BUF' or 'LAL'.")
    metric: str = Field(
        description=(
            "The number that justifies this move, with its unit — '22.3 proj pts', '4 games left', '£8.5m, 6.2 xPts'."
        )
    )
    rationale: str = Field(description="Why this move helps. Tactical and specific, no filler.")
    replaces: str = Field(
        default="",
        description="Counterpart player being dropped, benched or transferred out. Empty when there is none.",
    )
    replaces_rationale: str = Field(default="", description="Why that counterpart is the right one to move.")


Tone = Literal["neutral", "good", "warning"]
"""Whether a figure should pull the eye. Named so a provider computing one can
say so in its signature rather than returning a bare string."""


class Stat(BaseModel):
    """One headline figure: where the team stands before any reading happens.

    Computed by the provider from league state, never by the model — these are
    exact and a hallucinated rank or bank balance would be worse than none.
    """

    label: str = Field(description="Short name in the league's own vocabulary: 'Bank', 'Free transfers'.")
    value: str = Field(description="Already formatted for display, with its unit: '£2.5m', '340,112', '0-0'.")
    tone: Tone = Field(
        default="neutral",
        description=(
            "Whether this figure should pull the eye. 'warning' for something costing points now — "
            "points left on the bench, an expiring allowance — and 'good' for headroom worth spending."
        ),
    )


class Spot(BaseModel):
    """One place in a lineup, or one player on a bench.

    Competition-neutral on purpose: a slot is "FLEX" in the NFL and "" in the
    Premier League, where a formation has positions but not named places, and
    both render the same.
    """

    player_id: str = Field(default="", description="Identifier this competition uses, for opening the player.")
    slot: str = Field(default="", description="Named place in the lineup, where the competition has them.")
    player: str
    detail: str = Field(description="Position, club and opponent, as that competition words it.")
    value: str = Field(description="The forward-looking number, with its unit.")
    tone: Tone = "neutral"


class Side(BaseModel):
    """One team in a matchup — yours, or the one you are playing."""

    name: str
    detail: str = Field(default="", description="Record, manager, or however the league identifies a team.")
    points: str = Field(default="", description="What they have scored, or are projected to.")
    lineup: list[Spot] = Field(default_factory=list)
    bench: list[Spot] = Field(default_factory=list)


class PlayerQuery(BaseModel):
    """How much of a player list to return, in what order, and which of it.

    A football league's free-agent pool is four thousand players, so the list
    is a window onto a ranking rather than the ranking itself — which means
    the sort has to happen where the whole list is, not in the browser holding
    one page of it.
    """

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    sort: str = Field(default="", description="Column to order by. Empty means the competition's own ranking.")
    descending: bool = True
    position: str = Field(default="", description="Keep only this position. Empty keeps all.")
    search: str = Field(default="", description="Substring match across a row's own values.")


class PlayerPage(BaseModel):
    """One window onto a player list, and how much there is to page through."""

    players: list[PlayerCard] = Field(default_factory=list)
    total: int = Field(default=0, description="Rows matching the filters, before the window.")
    offset: int = 0
    positions: list[str] = Field(
        default_factory=list,
        description="Every position in the unfiltered pool, so a filter can be offered without guessing.",
    )


class PlayerCard(BaseModel):
    """A player as a row in a roster table.

    `columns` is the competition's own vocabulary — the Premier League sends
    Price and xPts, the NFL sends Slot — so a client renders whatever keys
    arrive rather than being taught each one. What sits beside it is what a
    table needs and a column should not be: an identifier to open, and whether
    the row wants attention.
    """

    player_id: str
    columns: dict[str, str]
    values: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "The number behind a formatted column, for the columns that have one — "
            "'Price' reads '£15.5m' and sorts as 15.5. Sorting the string instead puts "
            "£9.0m above £15.5m, and parsing it back means teaching every client each "
            "competition's units."
        ),
    )
    tone: Tone = "neutral"


class StatGroup(BaseModel):
    """A handful of related figures under a heading.

    Twenty numbers in one list is a wall; the same twenty under "This week",
    "Season" and "Set pieces" can be read without looking for anything.
    """

    title: str
    stats: list[Stat] = Field(default_factory=list)


NOT_APPLICABLE = "N/A"
"""What a cell reads where a period has no answer at all.

Part of the contract rather than a formatting choice: a nought is an answer and
this is the absence of one, and every client that dims one and not the other is
matching on this exact string.
"""


class StatRow(BaseModel):
    """One measure, across every column of a table."""

    label: str
    values: list[str] = Field(
        description=(
            f"One per column, in the same order. {NOT_APPLICABLE!r} where that column has no "
            "answer — distinct from '0', which is an answer."
        )
    )
    tone: Tone = "neutral"


class StatTable(BaseModel):
    """The same measures across several periods, so they can be read across.

    A stack of per-season groups makes you hold last year's goals in your head
    while you scroll to this year's. A table puts them on one line, which is
    the whole reason anybody looks at more than one season.
    """

    title: str
    columns: list[str] = Field(description="Period labels, newest first: ['2026/27', '2025/26', '2024/25'].")
    rows: list[StatRow] = Field(default_factory=list)


class PlayerDetail(BaseModel):
    """Everything worth knowing about one player, on demand.

    Fetched when someone asks rather than carried by every row: the interesting
    numbers differ per competition and there are a dozen of them, which is a table
    nobody can read attached to a payload nobody needs.
    """

    player_id: str
    name: str
    position: str
    team: str = Field(description="The club as a table spells it: 'DET', 'TOT'.")
    team_name: str = Field(
        default="",
        description=(
            "The same club in full — 'Detroit Lions', 'Tottenham Hotspur'. A drawer has room "
            "for the name a person would say, where a column has room for three letters. "
            "Empty falls back to `team` rather than leaving the line blank."
        ),
    )
    team_logo_url: str = Field(
        default="",
        description="The club's crest on the platform's own CDN, or empty where it has none.",
    )
    headline: str = Field(
        default="",
        description=(
            "The one figure this player is judged on, bare — '22.3', not '22.3 proj pts'. "
            "Empty when there is none, which is not the same as zero."
        ),
    )
    headline_label: str = Field(
        default="",
        description=(
            "What that figure is: 'projected this week', 'xPts this week'. When `headline` is "
            "empty this stands alone and says why there is no figure, so it reads as a sentence "
            "rather than as a number that failed to arrive."
        ),
    )
    note: str = Field(default="", description="Injury or availability news, in the platform's words.")
    url: str = Field(
        default="",
        description="This player on the platform's own site, where one exists.",
    )
    image_url: str = Field(
        default="",
        description=(
            "Portrait on the platform's own CDN, or empty where that competition has none. "
            "A URL rather than bytes: it is the client that has a cache for it."
        ),
    )
    tone: Tone = "neutral"
    groups: list[StatGroup] = Field(default_factory=list)
    tables: list[StatTable] = Field(
        default_factory=list,
        description="Comparisons across periods, which a list of groups cannot show.",
    )


class Swap(BaseModel):
    """A change the numbers already imply, before anyone has judged them."""

    start: str
    out: str = Field(default="", description="Who comes out. Empty when a place was unfilled.")
    gain: str


ActionKind = Literal["lineup", "waiver", "trade"]

Decision = Literal["AGREE", "OVERRULE", "WAIT"]
"""AGREE: make the move. OVERRULE: do not, whatever the numbers say. WAIT: it
turns on news due before the deadline — a questionable player's status."""


def task_id(position: int) -> str:
    """How the prompt names the to-do item at `position` (from 1), and how a
    verdict refers back to it. One function, so the two cannot drift apart."""
    return f"T{position}"


class TaskVerdict(BaseModel):
    """The model's judgement on one computed to-do item."""

    task: str = Field(description="The item's id exactly as listed, e.g. 'T1'.")
    decision: Decision = Field(
        description=(
            "AGREE to make the move. OVERRULE when the role, matchup or news says otherwise. "
            "WAIT when it turns on news due before the deadline."
        )
    )
    reason: str = Field(description="One sentence, grounded in role, matchup or news — never the projection alone.")


Urgency = Literal["now", "soon", "later"]
"""now: costs points this week if left alone. soon: worth doing before this
week's next deadline. later: planning for a week still to come."""


class Action(BaseModel):
    """One decision the week asks of the manager, and why it is one.

    Computed from league state, never by a model: a starter ruled out or a slot
    left empty is a fact, and the list has to be right before anything is
    asked to judge it.
    """

    kind: ActionKind
    urgency: Urgency
    key: str = Field(
        default="",
        description=(
            "Which decision this is — the hole it fills or the swap it makes — stable while the "
            "decision stays the same one, so a verdict finds its row again."
        ),
    )
    title: str = Field(description="The move, as an instruction: 'Start Jordyn Tyson over Chris Olave'.")
    reason: str = Field(description="Why, in the league's own facts: 'Olave is ruled out. +11.2 proj pts'.")
    when: str = Field(
        default="",
        description=(
            "The deadline, as a label: 'before kickoff, Thu 22 Oct', 'week 8'. Empty when the "
            "platform publishes none — a guessed deadline is worse than no deadline."
        ),
    )
    player_id: str = Field(default="", description="The player the move turns on, to open their detail.")
    replaces: str = Field(
        default="",
        description=(
            "The player the move takes out of the lineup, by id — empty where it fills an empty "
            "slot or moves nobody. With `player_id`, what the move does to a lineup."
        ),
    )
    drop: str = Field(
        default="",
        description=(
            "For a pickup, who to release to make room, by id — empty where the roster has a spot "
            "open, or the move adds nobody."
        ),
    )
    win_change: float | None = Field(
        default=None,
        description=(
            "How much the move changes the chance of winning this week, from simulating the "
            "matchup — 0.028 for +2.8 points of probability."
        ),
    )
    evidence: list[Stat] = Field(
        default_factory=list,
        description=(
            "What the move rests on beyond the projection, one line per player it involves — "
            "the matchup and the role behind the number. Empty where nothing has been played yet."
        ),
    )
    verdict: TaskVerdict | None = Field(
        default=None,
        description="The model's judgement, once a report has been run. None before, and for an item it skipped.",
    )
    hidden: Literal["dismissed", "snoozed"] | None = Field(
        default=None, description="Hidden by the manager's own decision: dismissed, or snoozed for now."
    )
    snoozed_until: datetime | None = Field(default=None, description="When a snooze runs out.")
    resurfaced: bool = Field(
        default=False,
        description="Whether a dismissed item has changed since, and so is back.",
    )

    @computed_field
    @property
    def fingerprint(self) -> str:
        """What this item currently says, so a verdict on an older version of it reads as stale.

        Everything a judgement rested on and nothing it produced: the move,
        the reason, the deadline and the evidence — not the verdict itself.
        """
        said = [self.title, self.reason, self.when, [[line.label, line.value] for line in self.evidence]]
        return hashlib.sha256(json.dumps(said).encode("utf-8")).hexdigest()[:12]


class ItemState(BaseModel):
    """What the manager has decided about one to-do item.

    Dismissed against a fingerprint rather than for good: "not this" is a
    judgment about the item as it read, and an item that changes — new news,
    a different gain — is new information, which brings it back.
    """

    key: str
    dismissed_as: str = Field(default="", description="The fingerprint the item had when dismissed; empty if not.")
    snoozed_until: datetime | None = Field(default=None, description="Hidden until then, aware UTC; None if not.")


class ItemDecision(BaseModel):
    """One decision about one to-do item, as the page sends it."""

    key: str = Field(min_length=1)
    decision: Literal["dismiss", "snooze", "restore"]
    fingerprint: str = Field(default="", description="For dismiss: the item as it read when dismissed.")
    until: datetime | None = Field(default=None, description="For snooze: when it comes back, with its offset.")

    @model_validator(mode="after")
    def _says_enough(self) -> ItemDecision:
        """A dismissal names what it dismissed, a snooze when it ends; anything less is unreadable."""
        if self.decision == "dismiss" and not self.fingerprint:
            raise ValueError("a dismissal needs the fingerprint of the item it dismisses")
        if self.decision == "snooze" and (self.until is None or self.until.tzinfo is None):
            raise ValueError("a snooze needs an end time with its offset")
        return self


class Summary(BaseModel):
    """Where a team stands, with no analysis in it.

    Everything here is read or computed from league state, so it is available
    the moment a page opens rather than after a model has answered.
    """

    headline: list[Stat] = Field(default_factory=list)
    mine: Side | None = None
    opponent: Side | None = None
    """Absent when the week has no fixture, which is not a nil-nil scoreline."""

    swaps: list[Swap] = Field(default_factory=list)
    """Changes the projections imply. Exact, and the report's job is to endorse
    or overrule them rather than to find them."""

    actions: list[Action] | None = None
    """What to do about the week, most urgent first. None where a competition
    computes none yet, which is not the same answer as an empty list: nothing
    to do."""

    fixtures: list[Stat] = Field(default_factory=list)
    """What a player's own row cannot say about his club's week: a blank, a double.
    Empty where the rows and the to-do list already carry it."""

    boosts: StatGroup | None = Field(
        default=None,
        description=(
            "One-time advantages the manager can spend, and what has become of each — "
            "carrying its own title, because the league names them: FPL calls them chips. "
            "None in a competition that has no such thing."
        ),
    )

    window: str = Field(
        default="",
        description=(
            "When this week actually is, already formatted — 'Week 1 · Sep 11-15', "
            "'GW 2 · deadline Sat 22 Aug 10:30'. A week with no dates on it is a number."
        ),
    )

    forecast: Forecast | None = None
    """The matchup simulated, where the competition can be. None where it cannot
    or there is no opponent this week."""


# ── simulating a matchup ────────────────────────────────────────────────


@dataclass(frozen=True)
class Outcomes:
    """One player's week as a range of equally likely scores.

    What the simulation draws from. The provider builds it — from his own
    games, his position's, and this week's projection — so the engine never
    needs to know which sport it is.
    """

    player_id: str
    name: str
    projection: float
    samples: tuple[float, ...]
    """Equally likely full-game scores. Empty means he scores only `floor`."""

    plays: float = 1.0
    """The chance he plays at all; otherwise he adds nothing past `floor`."""

    floor: float = 0.0
    """Points already on the board — what a game under way has given him so far."""

    remaining: float = 1.0
    """How much of a full game is still to come: 1 before kickoff, 0 once it is over."""

    projection_error: float = 0.0
    """Spread of a factor around 1 that scales his whole game in each simulated week —
    for how far the projection his range is centred on may itself be off."""

    group: str = ""
    """Players whose weeks rise and fall together — a quarterback and his receivers.
    Empty for a player whose week is his own."""

    shared_error: float = 0.0
    """The part of `projection_error` everyone in `group` shares: one factor per group per
    simulated week. Taken out of his own share rather than added to it, so his range on
    its own is the same either way and only how it moves with his teammates changes."""


@dataclass(frozen=True)
class LineupMove:
    """One change to the manager's lineup the simulation should price."""

    key: str
    title: str
    out: tuple[str, ...]
    """Player ids the move takes out of the lineup."""

    into: tuple[Outcomes, ...]
    """Who comes in instead."""


@dataclass(frozen=True)
class MatchupInput:
    """Both lineups, the moves to price, and a seed so the answer holds still between reloads."""

    mine: tuple[Outcomes, ...]
    theirs: tuple[Outcomes, ...]
    moves: tuple[LineupMove, ...] = ()
    seed: int = 0


@dataclass(frozen=True)
class PlayedMatchup:
    """A matchup already played, as it stood before kickoff — what a backtest scores the simulation on."""

    week: int
    matchup: MatchupInput
    mine: float
    theirs: float


class MarginRange(BaseModel):
    """How the margin falls across the simulated weeks: positive is a win."""

    low: float = Field(description="Tenth percentile: four weeks in five end above it.")
    median: float
    high: float = Field(description="Ninetieth percentile: four weeks in five end below it.")


class Forecast(BaseModel):
    """The week played many times over, and what each move does to it."""

    win: float = Field(description="Chance of winning, a tie counting half.")
    margin: MarginRange
    simulations: int
    moves: dict[str, float] = Field(
        default_factory=dict, description="Each move's key, and the chance of winning with it."
    )
    best_move: str = Field(
        default="", description="The move that most raises the chance, if any does; empty otherwise."
    )


class PickupChance(BaseModel):
    """What one available player would do to this week's chance of winning.

    Priced at his best legal start: every slot he could fill, against whoever
    he would push out, and the one that helps most — or hurts least, since a
    deep league's wire mostly hurts, and by how much is still the question.
    """

    player_id: str
    win_change: float = Field(description="The chance of winning with him started, less the chance without.")
    title: str = Field(description="The start that gets it, in the manager's words: 'Start X over Y'.")


# ── simulating a season ─────────────────────────────────────────────────


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
    usual: float = Field(description="What your best lineup projects in a typical one of these weeks.")
    missing: list[str] = Field(
        default_factory=list, description="Regular starters who will not play that week, and why: 'Josh Allen (bye)'."
    )
    short: bool = Field(description="Whether the week falls far enough below the usual to act on.")
    fix: str = Field(default="", description="The pickup that closes most of the gap, and who to drop for him.")
    gain: float = Field(default=0.0, description="What that pickup adds to the week's best lineup.")


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
    """The same for theirs: a trade that leaves them worse off is not one they will take."""
    scoring: tuple[TeamWeek, ...]
    """Both teams' scoring in each week the trade changes, replacing their rows in the season."""


@dataclass(frozen=True)
class TradeMarket:
    """The rest of the season, and the trades worth playing it out with."""

    season: SeasonInput
    options: tuple[TradeOption, ...]


class TradeIdea(BaseModel):
    """A trade worth offering, priced in what it does to the playoff race."""

    team_id: str
    team: str = Field(description="The manager to offer it to.")
    giving: list[str]
    receiving: list[str]
    playoffs: float = Field(description="Your chance of a playoff place with the trade made.")
    playoffs_change: float = Field(description="That chance less your chance without it.")
    their_playoffs_change: float = Field(description="The same for the other side: what you would hand a rival.")
    points: float = Field(description="Your starters' projected points a week, with the trade less without it.")
    their_points: float = Field(description="The same for theirs, which is the case for them saying yes.")


class CalibrationBucket(BaseModel):
    """Matchups the simulation gave a similar chance, and how often that side won."""

    low: float
    high: float
    matchups: int
    predicted: float
    won: float


class RangeScore(BaseModel):
    """How well players' ranges held what they then scored."""

    players: int = Field(description="Player-games scored.")
    inside: float = Field(description="Share whose score fell between the 10th and 90th percentile: 0.8 if right.")
    below: float = Field(description="Share below the 10th percentile: 0.1 if right.")
    above: float = Field(description="Share above the 90th percentile: 0.1 if right.")
    loss: float = Field(
        description="Mean quantile loss across the deciles, in points: lower is a sharper, truer range."
    )


class Calibration(BaseModel):
    """How the simulation's chances compared with what happened."""

    matchups: int
    brier: float = Field(description="Mean squared error of the chances; 0 is perfect, 0.25 is a coin flip.")
    buckets: list[CalibrationBucket] = Field(default_factory=list)


class ScheduleRow(BaseModel):
    """One week of your own season, played or still to come."""

    label: str = Field(description="What the league calls the week: 'Week 3', 'GW 12'.")
    date: str = Field(default="", description="When it is played, in the reader's words: 'Sep 14', 'Sat 13 Sep'.")
    opponent: str = Field(default="", description="Who you play. Empty on a bye, which is not an opponent named 'bye'.")
    detail: str = Field(default="", description="Their record, or however the league identifies them.")
    result: str = Field(default="", description="The score once it is played, and nothing before that.")
    tone: Tone = "neutral"
    is_current: bool = False
    """The week in progress, so a long table can say where you are in it."""
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


class ActivityRow(BaseModel):
    """One thing somebody in the league did."""

    when: str = Field(default="", description="Already formatted; a raw epoch is not a date.")
    who: str = Field(default="", description="The manager, not the roster id.")
    what: str = Field(description="Add, drop, trade, waiver — in the platform's own vocabulary.")
    detail: str = Field(default="", description="The players involved.")
    tone: Tone = "neutral"


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


class ScoutReport(BaseModel):
    """A scouting report for any competition: the model's judgement, with the week's own figures and items.

    What the model writes is `ScoutAnswer`, in `application/formats.py`; the
    engine adds what it does not get to write, so nothing here asks it to
    leave a field alone.
    """

    situation: str = Field(description="Where the team stands: the matchup, the run of fixtures, the league position.")
    focus: list[str] = Field(
        description=(
            "What this week turns on — close categories, thin positions, players on a bye. "
            "Short labels, e.g. ['BLK', 'FG%'] or ['RB depth', 'QB bye']."
        )
    )
    moves: list[Move] = Field(
        description="Recommended moves, most valuable first — only those the to-do list does not already hold."
    )
    strategy: str = Field(description="One-sentence summary of the plan.")
    verdicts: list[TaskVerdict] = Field(
        default_factory=list,
        description="Exactly one per to-do item, by its id. Empty when the prompt lists no to-do items.",
    )
    tasks: list[Action] = Field(
        default_factory=list, description="The to-do items as computed, each carrying its verdict."
    )

    headline: list[Stat] = Field(
        default_factory=list, description="Figures read straight from the platform, never written by the model."
    )


class Subject(BaseModel):
    """What a conversation is about: one to-do item, by its key, or one player.

    A question is asked of something on screen. Naming the thing is what lets
    the conversation be seeded with that thing and not the whole week.
    """

    kind: Literal["task", "player"]
    key: str = Field(description="The to-do item's key, or the player's id.")


WireDecision = Literal["ADD", "WATCH", "PASS"]
"""ADD: claim him now. WATCH: not yet, but his situation could change that.
PASS: not for this roster."""


class PlayerCall(BaseModel):
    """The model's call on one available player, shown on his row."""

    player_id: str = Field(description="The player's id exactly as listed, e.g. '8155'.")
    decision: WireDecision = Field(
        description="ADD to claim now; WATCH if a change in his situation would make him worth it; PASS otherwise."
    )
    drop: str = Field(default="", description="For ADD, who on the roster makes way. Empty otherwise.")
    reason: str = Field(description="One sentence, grounded in role, matchup or news — never the projection alone.")
    judged_at: datetime | None = Field(default=None, description="When the call was made.")
    stale: bool = Field(
        default=False,
        description="Whether the player's situation has changed since the call.",
    )


def answer_scope(kind: str, *about: str) -> str:
    """What a kept answer is about: the kind of call, then whose and of what.

    `("scout", "NFL (Sleeper)", league)` for a week's judgment;
    `("wire", "NFL (Sleeper)", league, player)` for one free agent's call.
    One answer is kept per scope, so the scope is as fine as the answer.
    """
    return ":".join((kind, *about))


class Remembered[AnswerT: BaseModel](BaseModel):
    """A model's answer, kept with exactly what it was given.

    Every call to a model goes through the same keeping: asked again only
    when what it would be given has changed, shown again on a reload without
    asking, and marked stale where its subject has moved on since.
    """

    answer: AnswerT
    inputs: str = Field(description="A digest of what the answer was given; a fresh ask compares against it.")
    answered_at: datetime


class TradeVerdict(BaseModel):
    """Evaluation of a proposed trade, in any competition.

    Field names are in whatever currency the league scores in: `gains` holds
    categories in a 9-cat league and position depth in a points league.
    """

    verdict: Literal["ACCEPT", "REJECT", "COUNTER"] = Field(description="The recommendation.")
    verdict_detail: str = Field(description="One or two sentences justifying the verdict.")
    gains: list[str] = Field(
        description=(
            "What this trade improves. Short labels in the league's own currency — "
            "['REB', 'BLK'] for categories, ['RB depth'] for points leagues."
        )
    )
    losses: list[str] = Field(description="What this trade weakens, in the same terms.")
    impact: str = Field(description="Net change in the league's scoring terms, referencing recent form.")
    schedule: str = Field(
        description="How the fixtures or remaining games compare, especially through the playoff weeks."
    )
    risk: str = Field(
        description=(
            "Availability risk on the incoming side: shutdown on a tanking team, injury designation, or rotation risk."
        )
    )
    strategy: str = Field(description="What to do next, including any counter-offer worth making.")


@dataclass
class TradeProposal:
    """Two lists of names, as a person described the trade.

    Names rather than identifiers because this is what somebody typed, and
    resolving them to players is a separate step that can fail — one side of a
    trade naming a player who is not in the league is a thing to say, not a
    thing to guess at.
    """

    giving: list[str] = field(default_factory=list)
    receiving: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """A trade needs both halves. One-sided is a drop, and not this."""
        return bool(self.giving) and bool(self.receiving)


@dataclass
class CompetitionContext:
    """A rendered prompt plus the parts it was assembled from.

    Keeping the parts lets a follow-up chat be seeded with a briefing rather
    than the whole prompt, which is resent on every turn and is dominated by the
    candidate pool — the players that were considered and passed over.
    """

    prompt: str
    situation: str = ""
    constraints: str = ""
    extra: str = ""
    roster_lines: dict[str, str] = field(default_factory=dict)
    candidate_lines: dict[str, str] = field(default_factory=dict)
    headline: list[Stat] = field(default_factory=list)
    """Exact figures for the report header, read from league state rather than written by the model."""
    tasks: list[Action] = field(default_factory=list)
    """The to-do items the prompt lists, in order, so a verdict naming `task_id(n)` finds its item."""
    targets: dict[str, str] = field(default_factory=dict)
    """Each subject's own lines in the prompt, keyed by its id — what an answer
    kept per subject was given, and so what tells whether it is still current."""

    def briefing(self, report: ScoutReport) -> str:
        """A compact context for follow-up questions about `report`.

        Carries the situation, constraints and full roster — what a "why that
        drop?" needs — plus only the candidates actually named. Says so, so the
        model declines rather than inventing numbers for a player it cannot see.
        """
        named = {m.player for m in report.moves} | {m.replaces for m in report.moves if m.replaces}
        kept = [line for name, line in self.candidate_lines.items() if name in named]

        sections = [
            "This is a condensed briefing on a report you just produced.",
            self.situation.strip(),
            self.constraints.strip(),
            self.extra.strip(),
            "CURRENT ROSTER:\n" + "".join(self.roster_lines.values()).strip(),
            "PLAYERS NAMED IN THE REPORT:\n" + ("".join(kept).strip() or "(none)"),
            (
                "NOTE: the full candidate pool is not included here. If asked about a player "
                "not shown above, say you would need to re-run the report rather than "
                "estimating their numbers."
            ),
        ]
        return "\n\n".join(s for s in sections if s)


# `Summary.forecast` names a model defined after it.
Summary.model_rebuild()
