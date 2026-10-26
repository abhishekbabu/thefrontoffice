"""What the model is asked to write: the answer formats the engines hand to the `AnalysisModel` port.

Apart from the domain's own models because they answer a different question.
A `ScoutReport` is the judged week a page shows — the platform's figures, the
computed to-do items, the model's verdict on each. What the model writes is
only the judgement, and a format that held the rest had to tell it, field by
field, to leave them alone: the prompt contract leaking into the domain, and
the domain changing whenever a prompt did. So the model fills these, every
field of them, and the engine builds the domain's answer from what it wrote.

Every description here is read by the model, as the schema it is held to.
"""

from pydantic import BaseModel, Field

from thefrontoffice.domain.models import Move, TaskVerdict, WireDecision


class ScoutAnswer(BaseModel):
    """The model's judgement of a week."""

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
