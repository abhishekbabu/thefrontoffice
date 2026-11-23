"""The league's recent moves, as a row per transaction: who went where, and who made it."""

from typing import Literal

from pydantic import BaseModel, Field


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
