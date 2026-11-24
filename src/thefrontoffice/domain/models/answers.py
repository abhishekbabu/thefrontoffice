"""What the model is asked and answers: reports, calls on players and trades, and their context."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from thefrontoffice.domain.models.values import Stat
from thefrontoffice.domain.models.week import Action, Move


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
    untouchable: list[str] = Field(default_factory=list)
    """Players the trade gives away that the manager marked untouchable, by name: the engine's, read off the
    league, never the model's. Not a refusal: the manager proposed it, and the evaluation says so."""


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
    untouchable: frozenset[str] = frozenset()
    """Your players the manager marked untouchable, by name as the prompt writes them. A model's move that
    drops, trades or sells one is not shown, whatever it argues."""
