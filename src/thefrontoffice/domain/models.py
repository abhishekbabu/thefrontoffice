"""Competition-agnostic report types.

Competitions differ in almost every detail — categories versus points, adds
versus a transfer budget, head-to-head versus league rank — but a report has
the same shape in each: read the situation, propose a ranked set of moves,
summarize the plan. One renderer, one chat-seeding path and one UI serve them all.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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


Tone = Literal["neutral", "good", "warning"]

Better = Literal["higher", "lower"]
"""Which way a figure improves, so one set beside another can be judged: most yards, fewest fumbles."""
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
    url: str = Field(
        default="",
        description="Where the figure comes from, to open: the article a headline is from. Empty for most.",
    )
    better: Better | None = Field(
        default=None,
        description="Which way this figure improves; null where it does not compare, like an opponent or a college.",
    )
    hint: str = Field(
        default="",
        description="What the label means, where it is the app's own measure rather than the league's: a tooltip.",
    )


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


PAGE_SIZE = 50
"""Rows a page of a player list holds unless the caller asks for another number."""

MAX_PAGE = 200
"""The most rows one page may hold: as many as a screen could ever show at once."""


class PlayerOrder(BaseModel):
    """Which column a player list is ordered by, and which way.

    One rule for every list, whether a page of the wire or a whole roster:
    the number behind a formatted column where the card has one — "£15.5m"
    sorted as text sits below "£9.0m" — and rows with nothing in the column
    kept last in both directions.
    """

    sort: str = Field(default="", description="Column to order by. Empty means the competition's own ranking.")
    descending: bool = True

    def ordered(self, cards: list[PlayerCard]) -> list[PlayerCard]:
        """`cards` in this order, or as they came where no column is named.

        Blanks stay last either way, which a sort key cannot express on its
        own: fold "is it missing" into the key and reversing the sort brings
        them to the top, where they push every real answer off the first page.
        """
        column = self.sort
        if not column:
            return cards
        numeric = any(column in card.values for card in cards)

        def has_value(card: PlayerCard) -> bool:
            return column in card.values if numeric else bool(card.columns.get(column))

        def key(card: PlayerCard) -> float | str:
            return card.values[column] if numeric else card.columns.get(column, "").casefold()

        present = [card for card in cards if has_value(card)]
        missing = [card for card in cards if not has_value(card)]
        return sorted(present, key=key, reverse=self.descending) + missing


class PlayerQuery(PlayerOrder):
    """How much of a player list to return, in what order, and which of it.

    A football league's free-agent pool is four thousand players, so the list
    is a window onto a ranking rather than the ranking itself — which means
    the sort has to happen where the whole list is, not in the browser holding
    one page of it.
    """

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=PAGE_SIZE, ge=1, le=MAX_PAGE)
    position: str = Field(default="", description="Keep only this position. Empty keeps all.")
    search: str = Field(default="", description="Substring match across a row's own values.")
    view: str = Field(
        default="", description="One of the page's `views` to list instead of the whole pool. Empty is the pool."
    )


class PlayerPage(BaseModel):
    """One window onto a player list, and how much there is to page through."""

    players: list[PlayerCard] = Field(default_factory=list)
    total: int = Field(default=0, description="Rows matching the filters, before the window.")
    offset: int = 0
    limit: int = Field(default=PAGE_SIZE, description="The window's size, which the next page steps by.")
    positions: list[str] = Field(
        default_factory=list,
        description="Every position in the unfiltered pool, so a filter can be offered without guessing.",
    )
    views: list[str] = Field(
        default_factory=list,
        description="Other lists of the pool the competition offers, by name: 'Trending', 'IR'. Empty where none.",
    )


PLAYER_COLUMN = "Player"
"""The column holding a player's name, in every competition's table."""

POSITION_COLUMN = "Pos"
"""The column holding a player's position, in every competition's table: what one position filter reads."""

STATUS_COLUMN = "Status"
"""The column holding a player's availability, in the platform's own words."""

SLOT_COLUMN = "Slot"
"""The column holding where a rostered player sits in the lineup."""

ColumnRole = Literal["player", "status", "slot"]
"""What a column is, for the few a table renders as more than text."""

_ROLES: dict[str, ColumnRole] = {PLAYER_COLUMN: "player", STATUS_COLUMN: "status", SLOT_COLUMN: "slot"}


class PlayerCard(BaseModel):
    """A player as a row in a roster table.

    `columns` is the competition's own vocabulary — the Premier League sends
    Price and xPts, the NFL sends Slot — so a client renders whatever keys
    arrive rather than being taught each one. What sits beside it is what a
    table needs and a column should not be: an identifier to open, and whether
    he will play.
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
    ruled_out: bool = Field(
        default=False,
        description=(
            "Whether his status means he will not play, rather than that he might not — "
            "decided by the provider, which knows its platform's words for it."
        ),
    )
    notes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "A cell's fuller reading, by column, where the cell abbreviates it — 'Bowers Q' reads "
            "'Without Brock Bowers (TE, Q): 6.10/game in 3 games · 8.60 with'. Shown as its tooltip."
        ),
    )

    @computed_field(
        description="The columns a table renders as more than text, by what they hold — so no client matches names."
    )
    @property
    def roles(self) -> dict[str, ColumnRole]:
        return {column: _ROLES[column] for column in self.columns if column in _ROLES}


FIT_COLUMN = "Fits"
"""The column where a provider says how a player fits your lineup: the inbound
side places the chance of winning beside it."""


class StatGroup(BaseModel):
    """A handful of related figures under a heading.

    Twenty numbers in one list is a wall; the same twenty under "This week",
    "Season" and "Set pieces" can be read without looking for anything.
    """

    title: str
    stats: list[Stat] = Field(default_factory=list)
    note: str = Field(default="", description="What the heading says about the group as a whole: '2 available'.")
    tab: str = Field(
        default="",
        description="Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.",
    )


NOT_APPLICABLE = "N/A"
"""What a cell reads where a period has no answer at all.

Part of the contract rather than a formatting choice: a nought is an answer and
this is the absence of one. Sent with every table as `StatTable.absent`, so a
client dims it without keeping its own copy of the string.
"""


class StatRow(BaseModel):
    """One line of a table across every column: a measure over the periods, or a game over the measures."""

    label: str
    values: list[str] = Field(
        description=(
            f"One per column, in the same order. {NOT_APPLICABLE!r} where that column has no "
            "answer — distinct from '0', which is an answer."
        )
    )
    tone: Tone = "neutral"
    better: Better | None = Field(default=None, description="Which way this measure improves; null where it does not.")
    best: list[int] = Field(
        default_factory=list,
        description=(
            "The cells holding the best figure, by index — set only on a comparison, and only where at "
            "least two figures compare and they differ."
        ),
    )


class StatTable(BaseModel):
    """Figures on a grid, so they can be read across as well as down.

    A stack of per-season groups makes you hold last year's goals in your head
    while you scroll to this year's. A table puts them on one line, which is
    the whole reason anybody looks at more than one season — and a game log is
    the same grid turned the other way, a game to a row and a measure to a column.
    """

    title: str
    tab: str = Field(
        default="",
        description="Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.",
    )
    columns: list[str] = Field(
        description=(
            "Column headings, the subject first: periods newest first, ['2026/27', '2025/26'], "
            "or measures, ['Pts', 'Snaps', 'Car']."
        )
    )
    rows: list[StatRow] = Field(default_factory=list)
    absent: str = Field(
        default=NOT_APPLICABLE,
        description="What a cell reads where its column has no answer, so a client can tell it from a figure.",
    )


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
    note: str = Field(
        default="",
        description=(
            "Injury or availability news, in words — 'Out', 'Questionable', FPL's own sentence — never a "
            "platform's bare code, which alone in a header reads as a figure ('O' as zero)."
        ),
    )
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
    rank: str = Field(
        default="",
        description="Where he ranks at his position this season: 'WR12'. Empty before he has played.",
    )
    owner: str = Field(
        default="",
        description=(
            "Whose roster he is on in this league — a team's name, or 'Free agent'. Empty where "
            "the league has no such thing, as in FPL, where any number of managers can hold one player."
        ),
    )
    tabs: list[str] = Field(
        default_factory=list,
        description=(
            "The drawer's tabs in the order shown, by the names its groups and tables carry. "
            "Empty is one page of everything, in the order sent."
        ),
    )
    groups: list[StatGroup] = Field(default_factory=list)
    tables: list[StatTable] = Field(
        default_factory=list,
        description="Comparisons across periods, which a list of groups cannot show.",
    )
    moves: list[ActivityRow] = Field(
        default_factory=list,
        description="Each league move he was part of, oldest first, as the league's activity shows it.",
    )
    moves_tab: str = Field(default="", description="Which tab his moves sit in, by name; empty for the first.")
    deferred: list[str] = Field(
        default_factory=list,
        description=(
            "Tabs whose sections are read only when opened, each from the player's tab route: they cost a "
            "request the rest of the drawer does not. Offered whether or not they turn out to hold anything."
        ),
    )


MAX_COMPARED = 4
"""The most players one comparison holds: past four, the columns stop fitting a screen."""


class PlayerComparison(BaseModel):
    """Players side by side: who each is, and the figures they share on one grid."""

    players: list[PlayerDetail] = Field(
        description="Each player's header, in the order asked: name, club, the one figure, owner. No groups or tables."
    )
    tables: list[StatTable] = Field(
        description=(
            "One per heading the measures came under — 'Week 11', 'Projected line', '2026 season' — each a row "
            "per measure and a column per player, in the order of `players`."
        )
    )


class PlayerRef(BaseModel):
    """A player found by name, enough to tell him from another and to open him."""

    player_id: str
    name: str
    detail: str = Field(default="", description="Position, club and owner: 'WR · DAL · Rival'.")


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

    games: int = 1
    """How many games he has left in the week, each drawn from `samples` on its own: one in
    football, as many as his club plays in basketball, nought for a player who will not play."""


@dataclass(frozen=True)
class LineupMove:
    """One change to the manager's lineup the simulation should price."""

    key: str
    title: str
    out: tuple[str, ...]
    """Player ids the move takes out of the lineup."""

    into: tuple[Outcomes, ...]
    """Who comes in instead."""

    made: bool = False
    """Already in `mine`, as the lineup a provider recommends: the move is written as its undo — `out` the
    player it started, `into` the one it benched — and what it is worth is the chance undoing it would cost."""


@dataclass(frozen=True)
class MatchupInput:
    """Both lineups, the moves to price, and a seed so the answer holds still between reloads."""

    mine: tuple[Outcomes, ...]
    theirs: tuple[Outcomes, ...]
    moves: tuple[LineupMove, ...] = ()
    seed: int = 0
    categories: CategoryMatchup | None = None
    """A week won category by category, simulated in place of `mine` and `theirs`, which are then empty."""
    provisional: bool = False
    """Whether games are still to be added to the week — a schedule not yet final — so any forecast of it runs short."""


@dataclass(frozen=True)
class ScoredCategory:
    """One category a week is won on, as the sum of one stat — or of one over another, for a percentage."""

    name: str
    made: str
    """The stat summed; for a percentage, the makes."""

    attempts: str = ""
    """The stat `made` is divided by, which makes this a percentage."""

    fewer_wins: bool = False
    """Won by the side with less of it: turnovers."""

    places: int | None = None
    """Decimal places the league compares it to — a percentage printed '.478' ties at three. None compares exactly."""


@dataclass(frozen=True)
class StatLines:
    """One player's week as figures: his recent games, each equally likely, and how many he has left."""

    player_id: str
    samples: tuple[tuple[float, ...], ...]
    """Each a game's figures, in `CategoryMatchup.stats` order. Empty means he adds nothing."""

    games: int
    """How many games he plays in what is left of the week."""


@dataclass(frozen=True)
class CategoryMatchup:
    """A week won category by category: what each side has so far, and each player's games still to come.

    The matchup goes to whoever wins more categories, a level count a tie — one result for
    the week, which is how a one-win league scores it and what a category league's week is
    called won by.
    """

    stats: tuple[str, ...]
    """The stats every figure below lists, in order."""

    categories: tuple[ScoredCategory, ...]
    mine: tuple[StatLines, ...]
    theirs: tuple[StatLines, ...]
    board_mine: tuple[float, ...]
    """Each stat's total so far, in `stats` order."""

    board_theirs: tuple[float, ...]


@dataclass(frozen=True)
class PlayedMatchup:
    """A matchup already played, as it stood before kickoff — what a backtest scores the simulation on."""

    week: int
    matchup: MatchupInput
    mine: float
    theirs: float


@dataclass(frozen=True)
class RangeSearch:
    """The settings that shape a competition's player ranges, as plain numbers a tuning run can search.

    Named and valued by the competition, so the search needs to know nothing
    about what each one means.
    """

    current: dict[str, float]
    """Each setting as the app runs with it."""

    grid: dict[str, tuple[float, ...]]
    """The values worth trying for each, the current one among them."""


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
    categories: dict[str, float] = Field(
        default_factory=dict,
        description="Each category's name and your chance of winning it, in a week won on categories; empty otherwise.",
    )
    provisional: bool = Field(
        default=False,
        description="Whether the week's schedule is not final yet, so the games it was played over are short.",
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


def calibration(called: Sequence[tuple[float, float]], width: float = 0.2) -> Calibration:
    """How a run of chances compared with what happened: each a chance and its result, one for won, nought for
    lost, a half for level — scored, and bucketed `width` apart by the chance given."""
    if not called:
        return Calibration(matchups=0, brier=0.0)
    edges = round(1 / width)
    buckets = []
    for step in range(edges):
        low, high = round(step * width, 9), round((step + 1) * width, 9)
        inside = [(c, o) for c, o in called if low <= c < high or (step == edges - 1 and c >= high)]
        if inside:
            buckets.append(
                CalibrationBucket(
                    low=low,
                    high=high,
                    matchups=len(inside),
                    predicted=sum(c for c, _ in inside) / len(inside),
                    won=sum(o for _, o in inside) / len(inside),
                )
            )
    return Calibration(matchups=len(called), brier=sum((c - o) ** 2 for c, o in called) / len(called), buckets=buckets)


OddsModel = Literal["hand-set", "fitted, independent", "fitted"]
"""The spreads a category league's odds can be checked under: those set by hand before any fit, the fitted
ones with every category taken as independent, and the fitted ones as the app runs them."""

ODDS_MODELS: tuple[OddsModel, ...] = get_args(OddsModel)


class OddsFit(BaseModel):
    """How far a category league's weeks strayed from what their games projected, over a season played."""

    season: str
    player_weeks: int = Field(description="Weeks of rostered-calibre players the fit is read from.")
    missed: float = Field(description="Share of their clubs' games those players sat out.")
    form: dict[str, float] = Field(description="Spread of a factor on a player's week in each count, by label.")
    rate: dict[str, float] = Field(description="The same on each percentage's makes, by label.")
    game: dict[str, float] = Field(description="One game's spread around a player's average, as a share of it.")
    typical: dict[str, float] = Field(description="A rostered player's game: a count's average, a percentage's rate.")
    kept: dict[str, float] = Field(
        description="The share of a player's distance from the typical game that his weeks bore out."
    )
    correlation: dict[str, dict[str, float]] = Field(
        description="How each category's miss moves with each other's, summed over a roster's players."
    )
    loadings: dict[str, float] = Field(description="Each category's share in the one swing they move with.")


class OddsCheck(BaseModel):
    """How one set of spreads called the categories and weeks of a season played, in leagues dealt from it."""

    season: str
    model: OddsModel
    weeks: int
    categories: Calibration = Field(description="Each category of each matchup, bucketed a tenth apart.")
    matchups: Calibration = Field(description="Each matchup's week, a level week a half.")


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


class ActivityMove(BaseModel):
    """One player a league move moved: who, and which way, for which team."""

    player_id: str = Field(
        description="Identifier this platform uses for the player, so his page opens; empty for FAAB a trade moved."
    )
    player: str
    position: str = ""
    team: str = Field(default="", description="His real-world club.")
    change: Literal["added", "dropped"]
    manager: str = Field(default="", description="Whose roster gained or lost him: two in a trade.")


class ActivityRow(BaseModel):
    """One thing somebody in the league did."""

    when: str = Field(default="", description="Already formatted; a raw epoch is not a date.")
    who: str = Field(default="", description="The manager, not the roster id.")
    what: str = Field(description="Add, drop, trade, waiver — in the platform's own vocabulary.")
    detail: str = Field(default="", description="The players involved.")
    is_mine: bool = False
    """Your own move, so it can be found among everyone else's."""
    moves: list[ActivityMove] = Field(
        default_factory=list, description="Each player it moved, for the move's own page. Empty where unknown."
    )
    bid: str = Field(default="", description="What a waiver claim was won with, already formatted; empty for none.")


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

    The first four fields are what the model wrote, as `ScoutAnswer` in
    `application/formats.py` describes them to it; the engine adds what it
    does not get to write, so nothing here asks it to leave a field alone.
    """

    situation: str
    focus: list[str]
    moves: list[Move]
    strategy: str
    tasks: list[Action] = Field(
        default_factory=list, description="The to-do items as computed, each carrying its verdict."
    )
    headline: list[Stat] = Field(
        default_factory=list, description="Figures read straight from the platform, never written by the model."
    )


PAGES = ("matchup", "schedule", "fixtures", "team", "trades", "free-agents", "league")
"""The pages of a league, by the name each has in its address."""


class Subject(BaseModel):
    """Something on screen a question is asked with: one to-do item, by its key, one player, or one page.

    Naming the thing is what lets the conversation be briefed on that thing
    and not the whole league.
    """

    kind: Literal["task", "player", "page"]
    key: str = Field(description=f"The to-do item's key, the player's id, or one of {PAGES}.")


WireDecision = Literal["ADD", "WATCH", "PASS"]
"""ADD: claim him now. WATCH: not yet, but his situation could change that.
PASS: not for this roster."""


class PlayerCall(BaseModel):
    """The model's call on one available player, shown on his row.

    What the model writes is `CallAnswer`, in `application/formats.py`; the
    engine adds when it was made and whether it still stands.
    """

    player_id: str
    decision: WireDecision
    drop: str = ""
    """For ADD, who on the roster makes way."""
    reason: str
    judged_at: datetime | None = Field(default=None, description="When the call was made.")
    stale: bool = Field(
        default=False,
        description="Whether the player's situation has changed since the call.",
    )


class Remembered[AnswerT: BaseModel](BaseModel):
    """A model's answer, kept with exactly what it was given.

    Every call to a model goes through the same keeping: asked again only
    when what it would be given has changed, shown again on a reload without
    asking, and marked stale where its subject has moved on since.
    """

    answer: AnswerT
    inputs: str = Field(description="A digest of what the answer was given; a fresh ask compares against it.")
    answered_at: datetime


class Judgment(Remembered[ScoutReport]):
    """A league's kept judgment of its week, as the week page reads it back."""

    due: bool = Field(
        default=False,
        description=(
            "Whether the week has moved on far enough to judge it again unasked: the to-do list holds "
            "an item this judgment never saw, or what it was given has changed and it is over twelve "
            "hours old. Never while the list is empty — there is nothing left to judge."
        ),
    )


TradeCall = Literal["ACCEPT", "REJECT", "COUNTER"]


class TradeVerdict(BaseModel):
    """Evaluation of a proposed trade, in any competition.

    Written by the model, as `TradeAnswer` in `application/formats.py`
    describes it. In whatever currency the league scores in: `gains` holds
    categories in a 9-cat league and position depth in a points league.
    """

    verdict: TradeCall
    verdict_detail: str
    gains: list[str]
    losses: list[str]
    impact: str
    schedule: str
    risk: str
    strategy: str


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
    candidate pool — the players that were considered and passed over. The
    briefing itself is `application/briefing.py`'s.
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
    worth: dict[str, float] = field(default_factory=dict)
    """What each player the prompt names is worth a game over the season, keyed by name as the
    prompt writes it — what a suggested add is weighed against the player it would drop. A
    position filled week to week by matchup is left out, since a season says nothing about it."""
    listed: frozenset[str] = frozenset()
    """Every player a to-do item already turns on, by name as the prompt writes it. A model's
    move about one of them is that item said a second time, and is not shown beside it."""
    movable: frozenset[str] | None = None
    """Every player a move could still name this week, by name: yours, and those nobody holds,
    whose game has not kicked off. A kept judgment's moves are read back through it, so a
    pickup for a game already played, or of a player someone else has since added, is not
    shown. None where the competition does not say, and every kept move stands."""


# ── browser capture ─────────────────────────────────────────────────────
# A platform whose API refuses this app can still be read the way its own pages
# read it: a script on one of those pages fetches what the app needs with the
# person's session and hands the responses over. The session never leaves the
# browser; only the bodies do.


class CaptureStep(BaseModel):
    """One response the app wants a browser to fetch."""

    path: str = Field(description="Below the plan's `base`, exactly as fetched and as handed back.")
    league: str = Field(default="", description="The league it belongs to; empty for one about the account.")


class CapturePlan(BaseModel):
    """What a browser should fetch next, given what the app already holds.

    Planned again after each hand-over: what one response holds (a league's
    current week, its teams) decides what the next round asks for. A browser
    stops when a plan asks for nothing it has not already fetched.
    """

    base: str = Field(description="The URL every step's path is fetched below, with the browser's session.")
    probe: str = Field(description="Fetched first: anything but 200 means the browser is not signed in.")
    steps: list[CaptureStep] = Field(default_factory=list)


class CapturedResponse(BaseModel):
    """One response a browser fetched: its body and nothing of the session that fetched it."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=1024)
    status: int
    body: str


class Capture(BaseModel):
    """What one round of a browser sync hands over."""

    model_config = ConfigDict(extra="forbid")

    profile: CapturedResponse
    """The probe's response, which says the session was signed in when the rest was fetched."""

    responses: list[CapturedResponse] = Field(max_length=2000)


class CaptureReceipt(BaseModel):
    """What one hand-over stored, and what it refused."""

    stored: int
    leagues: list[str] = Field(default_factory=list, description="Each league that had something stored, by key.")
    errors: list[str] = Field(default_factory=list, description="Each response refused, with why.")


class SessionStatus(BaseModel):
    """How the server's last read of a platform with the person's session cookie went."""

    fetched_at: datetime | None = None
    """When it last read anything with the cookie now set; None before it has, or once it is refused."""

    expired: bool = Field(default=False, description="Whether the platform refused the cookie now set.")


class CaptureStatus(BaseModel):
    """How fresh the capture is, for the page that offers the sync."""

    active: bool = Field(description="Whether the app reads this platform from the capture rather than its API.")
    synced_at: datetime | None = None
    """When a hand-over last stored anything; None before the first."""

    leagues: list[str] = Field(default_factory=list, description="The leagues captured this season, by name.")
    session: SessionStatus | None = None
    """How reading with the person's session cookie is going, where the app reads that way; None otherwise."""
