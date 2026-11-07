"""What can be done about a failure, for the conditions this app knows how to fix.

The domain describes a condition and names no command or button, because the
same error is read in a terminal and in a browser. This is where each inbound
adapter's way of fixing it lives, side by side, so the two cannot drift apart:
the web page offers `action`, the terminal prints `command`.
"""

from typing import Literal

from pydantic import BaseModel, Field

from thefrontoffice.domain.errors import ErrorCode

YAHOO_DEVELOPER_ACCESS = "https://sports.yahoo.com/developer/access/"
"""Where a Yahoo application applies for Fantasy Sports API access."""


class Remedy(BaseModel):
    """The one thing worth offering for a failure."""

    action: Literal["authorize", "settings", "retry", "link"] = Field(
        description=(
            "What the page offers: start the platform login, open Settings, ask again, or follow `url` off the app."
        )
    )
    label: str = Field(description="The control's words: 'Apply for API access'.")
    url: str = Field(default="", description="Where a link goes; empty for every other action.")
    command: str = Field(
        default="",
        description="What a terminal does instead, or empty where it has nothing to run.",
    )


REMEDIES: dict[ErrorCode, Remedy] = {
    "login_required": Remedy(
        action="authorize",
        label="Authorize Yahoo",
        command="Run `just yahoo-login` to authorize.",
    ),
    "access_not_approved": Remedy(
        action="link",
        label="Apply for API access",
        url=YAHOO_DEVELOPER_ACCESS,
        command=f"Apply at {YAHOO_DEVELOPER_ACCESS}, then `just yahoo-login --force`.",
    ),
    "ai_key_invalid": Remedy(action="settings", label="Open Settings"),
    "ai_unavailable": Remedy(action="settings", label="Open Settings"),
    # A platform that is down: waiting is the remedy, and asking again is the
    # one thing a page can do about it.
    "platform_unavailable": Remedy(action="retry", label="Try again"),
}


def remedy(code: ErrorCode) -> Remedy | None:
    """The remedy for `code`, or None where there is nothing to offer but the message."""
    return REMEDIES.get(code)
