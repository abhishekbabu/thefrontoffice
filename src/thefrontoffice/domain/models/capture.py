"""Browser capture.

A platform whose API refuses this app can still be read the way its own pages
read it: a script on one of those pages fetches what the app needs with the
person's session and hands the responses over. The session never leaves the
browser; only the bodies do.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
