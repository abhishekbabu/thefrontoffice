"""Small values every other model is built from: a stat as shown, and the tone it is read in."""

from typing import Literal

from pydantic import BaseModel, Field

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
