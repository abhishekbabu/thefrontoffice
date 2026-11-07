"""What the model is asked to write: the answer formats the engines hand to the `AnalysisModel` port.

Apart from the domain's own models because they answer a different question.
A `ScoutReport` is the judged week a page shows — the platform's figures, the
computed to-do items, the model's verdict on each. What the model writes is
only the judgement, and a format that held the rest had to tell it, field by
field, to leave them alone: the prompt contract leaking into the domain, and
the domain changing whenever a prompt did. So the model fills these, every
field of them, and the engine builds the domain's answer from what it wrote.

Every description here is read by the model, as the schema it is held to,
and these are the only model instructions outside a competition's prompt.
"""

from pydantic import BaseModel, Field

from thefrontoffice.domain.models import Decision, MoveAction, TradeCall, WireDecision, task_id


class MoveAnswer(BaseModel):
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


class VerdictAnswer(BaseModel):
    """The model's judgement on one computed to-do item."""

    task: str = Field(description=f"The item's id exactly as listed, e.g. '{task_id(1)}'.")
    decision: Decision = Field(
        description=(
            "AGREE to make the move. OVERRULE when the role, matchup or news says otherwise. "
            "WAIT when it turns on news due before the deadline."
        )
    )
    reason: str = Field(description="One sentence, grounded in role, matchup or news — never the projection alone.")


class ScoutAnswer(BaseModel):
    """The model's judgement of a week."""

    situation: str = Field(description="Where the team stands: the matchup, the run of fixtures, the league position.")
    focus: list[str] = Field(
        description=(
            "What this week turns on — close categories, thin positions, players on a bye. "
            "Short labels, e.g. ['BLK', 'FG%'] or ['RB depth', 'QB bye']."
        )
    )
    moves: list[MoveAnswer] = Field(
        description="Recommended moves, most valuable first — only those the to-do list does not already hold."
    )
    strategy: str = Field(description="One-sentence summary of the plan.")
    verdicts: list[VerdictAnswer] = Field(
        default_factory=list,
        description="Exactly one per to-do item, by its id. Empty when the prompt lists no to-do items.",
    )


class CallAnswer(BaseModel):
    """The model's call on one available player."""

    player_id: str = Field(description="The player's id exactly as listed, e.g. '8155'.")
    decision: WireDecision = Field(
        description="ADD to claim now; WATCH if a change in his situation would make him worth it; PASS otherwise."
    )
    drop: str = Field(default="", description="For ADD, who on the roster makes way. Empty otherwise.")
    reason: str = Field(description="One sentence, grounded in role, matchup or news — never the projection alone.")


class WireAnswer(BaseModel):
    """The model's calls on the players it was shown."""

    calls: list[CallAnswer] = Field(description="Exactly one per listed player, by id.")


class TradeAnswer(BaseModel):
    """The model's evaluation of a proposed trade, in whatever currency the league scores in."""

    verdict: TradeCall = Field(description="The recommendation.")
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


class TradeSides(BaseModel):
    """The two sides of a trade, as a person typed it."""

    giving: list[str] = Field(description="Full names of the players being given away.")
    receiving: list[str] = Field(description="Full names of the players being received.")
