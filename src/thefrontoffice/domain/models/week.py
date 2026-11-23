"""The week being played: lineups by spot, each side's total, and the moves proposed on it."""

import hashlib
import json
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, Field, computed_field, model_validator

from thefrontoffice.domain.models.players import StatGroup
from thefrontoffice.domain.models.values import Stat, Tone

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
    """One recommended action on one player, as the model judged it.

    How the model is asked to fill each field is `MoveAnswer`'s, in
    `application/formats.py`; this is what a report keeps and a page shows.
    """

    action: MoveAction
    player: str
    position: str
    team: str
    metric: str
    """The number that justifies the move, with its unit."""
    rationale: str
    replaces: str = ""
    """The counterpart dropped, benched or transferred out; empty where there is none."""
    replaces_rationale: str = ""

    @computed_field
    @property
    def title(self) -> str:
        """The move as an instruction, the way a to-do item words its own: 'Add Warren, drop Johnson'.

        Written here, once, so a page and a terminal phrase a move alike.
        """
        verb, join = MOVE_WORDS[self.action]
        rest = f"{join} {self.replaces}" if self.replaces and join else ""
        return f"{verb} {self.player}{rest}"


MOVE_WORDS: dict[MoveAction, tuple[str, str]] = {
    "ADD": ("Add", ", drop"),
    "DROP": ("Drop", ""),
    "START": ("Start", " over"),
    "BENCH": ("Bench", " for"),
    "TRANSFER": ("Bring in", " for"),
    "CAPTAIN": ("Captain", ""),
    "MONITOR": ("Watch", ""),
}
"""Each action's verb, and how it joins the player it `replaces`: empty where the
action takes nobody out, so a counterpart the model named anyway is not read as one."""


SpotScoring = Literal["projected", "live", "final"]


class Spot(BaseModel):
    """One place in a lineup, or one player on a bench.

    Competition-neutral on purpose: a slot is "FLEX" in the NFL and "" in the
    Premier League, where a formation has positions but not named places, and
    both render the same.
    """

    player_id: str = Field(default="", description="Identifier this competition uses, for opening the player.")
    slot: str = Field(default="", description="Named place in the lineup, where the competition has them.")
    player: str
    mark: str = Field(
        default="",
        description=(
            "A role the row carries beyond its place, as the league abbreviates it — FPL's captain "
            "'C' and vice-captain 'VC'. Shown as a chip beside the name; empty for most rows."
        ),
    )
    detail: str = Field(description="Position, club and opponent, as that competition words it.")
    value: str = Field(
        description="The number the row turns on, with its unit: a projection, or once his game has kicked off, what he has scored."
    )
    tone: Tone = "neutral"
    today: str = Field(
        default="",
        description=(
            "Whether he plays in the scoring period under way, where a lineup is set day by day: 'vs TOR today', "
            "'@ BOS live', 'no game today'. Empty where the competition sets lineups by the week, or it is unknown."
        ),
    )
    idle: bool = Field(
        default=False,
        description="He has no game today (`today`): a start there scores nothing until he is swapped out.",
    )
    kickoff: datetime | None = Field(
        default=None,
        description=(
            "When his game starts, in UTC, while it has not: the page shows it in the viewer's own zone, "
            "as the hour beside `today` where a lineup is set by the day. "
            "None once it has kicked off, and where the time is unknown."
        ),
    )
    scoring: SpotScoring | None = Field(
        default=None,
        description=(
            "Which kind of number `value` is: projected before his game, live while it is on, final "
            "after. None where the competition does not say."
        ),
    )
    scored: str = Field(
        default="",
        description="What he has scored, bare — empty until his game kicks off. Shown beside `projection`.",
    )
    projection: str = Field(
        default="",
        description=(
            "What he is projected, shown beside what he has scored on every row that says how it "
            "scores — the guess beside the answer, and before kickoff the only number there is."
        ),
    )
    line: list[Stat] = Field(
        default_factory=list,
        description=(
            "His figures in each category the league scores, in its order, where a row shows them as "
            "columns — a category week played, or his game today once it tips off. Labelled alike on every "
            "row of the side; empty for most."
        ),
    )


class Side(BaseModel):
    """One team in a matchup — yours, or the one you are playing."""

    name: str
    record: str = Field(
        default="",
        description=(
            "Their season record now, in the league's own terms: '7-4', '6W 1D 4L'. Empty where the "
            "league keeps none — a classic FPL table — or would not say."
        ),
    )
    detail: str = Field(default="", description="Anything else the league identifies a team by: 'GW12 picks'.")
    points: str = Field(default="", description="What they have scored, or are projected to.")
    lineup: list[Spot] = Field(default_factory=list)
    bench: list[Spot] = Field(default_factory=list)
    open_spots: int = Field(
        default=0,
        description=(
            "Roster spots the team holds nobody in, outside its reserve: room to add a player "
            "without dropping one. 0 where the roster is full or the league does not say."
        ),
    )
    reserve: list[Spot] = Field(
        default_factory=list,
        description=(
            "Players held in a slot that costs no roster spot and cannot start, such as injured reserve "
            "or taxi, in rows shaped like the bench's. Empty where the league has none."
        ),
    )


ActionKind = Literal["lineup", "waiver", "trade", "transfer", "chip"]
"""What a to-do item changes: the lineup, the roster by waiver or by trade, the squad by a transfer
against the market, or a one-time chip spent."""

Decision = Literal["AGREE", "OVERRULE", "WAIT"]
"""AGREE: make the move. OVERRULE: do not, whatever the numbers say. WAIT: it
turns on news due before the deadline — a questionable player's status."""


def task_id(position: int) -> str:
    """How the prompt names the to-do item at `position` (from 1), and how a
    verdict refers back to it. One function, so the two cannot drift apart."""
    return f"T{position}"


class TaskVerdict(BaseModel):
    """The model's judgement on one computed to-do item."""

    task: str
    """The item's id, as `task_id` numbered it."""
    decision: Decision
    reason: str


Urgency = Literal["now", "soon", "later"]
"""now: costs points this week if left alone. soon: worth doing before this
week's next deadline. later: planning for a week still to come."""


def urgency_rank(urgency: Urgency) -> int:
    """Where `urgency` sorts, most pressing first: its place in the literal, so the two cannot disagree."""
    return get_args(Urgency).index(urgency)


class ItemMark(BaseModel):
    """What the manager's decisions make of one to-do item as it reads now."""

    hidden: Literal["dismissed", "snoozed"] | None = Field(
        default=None, description="Hidden by the manager's own decision: dismissed, or snoozed for now."
    )
    snoozed_until: datetime | None = Field(default=None, description="When a snooze runs out.")
    resurfaced: bool = Field(
        default=False,
        description="Whether a dismissed item has changed since, and so is back.",
    )


MoveSide = Literal["in", "out"]
"""Whether a move brings a player in or takes him out."""

Pickup = Literal["streamer", "keeper"]
"""What an add is for: a streamer plays this week's games and goes again; a keeper is worth his spot for the
rest of the season."""

Held = Literal["starter", "bench", "reserve", "free agent", "waivers", "market"]
"""Where a player stands to the manager: in his lineup, on his bench, in a reserve slot, free to add, on
waivers (claimed, not added), or — in a game with no wire, where anybody can be bought — in the transfer market."""


class MovePlayer(BaseModel):
    """One player a to-do item moves, with the figures it is weighed on.

    Every player on an item carries the same rows in the same order, so the
    player coming in and the one going out read side by side as data — never
    parsed out of a sentence.
    """

    side: MoveSide = Field(description="Whether the move brings him in or takes him out.")
    player_id: str
    name: str
    position: str = ""
    team: str = Field(default="", description="His real-world club.")
    held: Held
    figures: list[Stat] = Field(
        default_factory=list,
        description="The rows he is compared on, labelled alike for every player on the item; '—' where he has none.",
    )

    def text(self) -> str:
        """'IN: Chimere Dike (WR, LV; free agent) — Snap% 66%, Proj 9.88': how a model reads him."""
        figures = ", ".join(f"{figure.label} {figure.value}" for figure in self.figures)
        about = ", ".join(part for part in (self.position, self.team) if part)
        return f"{self.side.upper()}: {self.name} ({about}{'; ' if about else ''}{self.held})" + (
            f" — {figures}" if figures else ""
        )


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
    pickup: Pickup | None = Field(
        default=None,
        description=(
            "For an add, what he is added for: 'streamer' (this week's games) or 'keeper' "
            "(the rest of the season). None for anything else, and where the league does not say."
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
    players: list[MovePlayer] = Field(
        default_factory=list,
        description=(
            "Who the move brings in and takes out, figure by figure, for a side-by-side reading. "
            "Empty where it moves one player or none: `evidence` says what it rests on then."
        ),
    )
    verdict: TaskVerdict | None = Field(
        default=None,
        description="The model's judgement, once a report has been run. None before, and for an item it skipped.",
    )
    stale: bool = Field(
        default=False,
        description="Whether the item has changed since `verdict` was given: a verdict on last night's news.",
    )
    mark: ItemMark = Field(default_factory=ItemMark, description="What the manager's own decisions make of the item.")
    chance: Stat | None = Field(
        default=None,
        description=(
            "`win_change` as it reads — '+2.8% to win', toned by its sign. Written where the "
            "week is presented, so a page and a terminal say it alike; None where unpriced."
        ),
    )

    @computed_field
    @property
    def fingerprint(self) -> str:
        """What this item currently says, so a verdict on an older version of it reads as stale.

        Everything a judgement rested on and nothing it produced: the move,
        the reason, the deadline, the evidence and the figures compared — not the verdict itself.
        """
        said: list[object] = [self.title, self.reason, self.when, [[line.label, line.value] for line in self.evidence]]
        if self.players:
            said.append([player.text() for player in self.players])
        return hashlib.sha256(json.dumps(said).encode("utf-8")).hexdigest()[:12]

    def lines(self) -> list[str]:
        """What the item rests on, as a model reads it: each player it moves, then each line of evidence.

        One rendering for every prompt that lists an item, so the judging
        prompt and a follow-up question name the players' roles alike.
        """
        return [player.text() for player in self.players] + [f"{line.label}: {line.value}" for line in self.evidence]


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


class WeekRange(BaseModel):
    """Which week a page shows, the week being played, and how far either way the season can be browsed."""

    week: int
    current: int
    """The week being played, or the next to be once the last is over: the one the to-do list is about."""
    first: int
    last: int
    """The league's final week, its playoffs included."""


class CategoryLine(BaseModel):
    """One scoring category of a category league's week: each side's figure, and who leads it."""

    name: str = Field(description="The category as the league abbreviates it: 'PTS', 'FG%'.")
    mine: str = Field(description="Your side's figure, as the league prints it; empty before any is recorded.")
    theirs: str = Field(description="The other side's figure, the same way.")
    lead: Literal["mine", "theirs", "even"] | None = Field(
        default=None,
        description=(
            "Who is ahead in it, with the category's own direction read in (fewer turnovers wins). "
            "None where there is nothing yet to compare."
        ),
    )
    win: float | None = Field(
        default=None,
        description="Your chance of winning the category by the week's end; None where the week is not forecast.",
    )


class Summary(BaseModel):
    """Where a team stands, with no analysis in it.

    Everything here is read or computed from league state, so it is available
    the moment a page opens rather than after a model has answered.
    """

    headline: list[Stat] = Field(default_factory=list)
    mine: Side | None = None
    opponent: Side | None = None
    """Absent when the week has no fixture, which is not a nil-nil scoreline."""

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

    categories: list[CategoryLine] = Field(
        default_factory=list,
        description=(
            "A category league's head-to-head, one line per category, in the league's order. "
            "Empty in a points league, and in a week with no opponent."
        ),
    )

    weeks: WeekRange | None = Field(
        default=None,
        description=(
            "Where this week sits in the season, for paging to another. "
            "None in a competition that shows only the week being played."
        ),
    )
