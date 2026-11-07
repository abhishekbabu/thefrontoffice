"""What can be done about a failure, for the conditions this app knows how to fix.

The domain describes a condition and names no command, button or file, because
the same error is read in a terminal and in a browser. This is where each
inbound adapter's way of fixing it lives, side by side, so the two cannot drift
apart: the web page offers `action`, the terminal prints `command`.
"""

from typing import Literal

from pydantic import BaseModel, Field

from thefrontoffice.domain.errors import ErrorCode, FrontOfficeError, LoginRequiredError

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
    platform: str = Field(default="", description="Whose login an authorize starts: 'yahoo'; empty otherwise.")
    command: str = Field(
        default="",
        description="What a terminal does instead, or empty where it has nothing to run.",
    )


SETTINGS = "Open Settings"

LOGINS: dict[str, Remedy] = {
    "yahoo": Remedy(
        action="authorize",
        label="Authorize Yahoo",
        platform="yahoo",
        command="Run `just yahoo-login` to authorize.",
    ),
}
"""Each platform's login, by the registry's name for the platform."""

REMEDIES: dict[ErrorCode, Remedy] = {
    "access_not_approved": Remedy(
        action="link",
        label="Apply for API access",
        url=YAHOO_DEVELOPER_ACCESS,
        command=f"Apply at {YAHOO_DEVELOPER_ACCESS}, then `just yahoo-login --force`.",
    ),
    "not_configured": Remedy(
        action="settings", label=SETTINGS, command="Set it in .env; `just doctor` shows what is set."
    ),
    "ai_key_invalid": Remedy(action="settings", label=SETTINGS, command="Correct it in .env."),
    "ai_unavailable": Remedy(action="settings", label=SETTINGS, command="Set one in .env to turn analysis on."),
    # A platform that is down: waiting is the remedy, and asking again is the
    # one thing a page can do about it.
    "platform_unavailable": Remedy(action="retry", label="Try again"),
}


def remedy(error: FrontOfficeError) -> Remedy | None:
    """The remedy for `error`, or None where there is nothing to offer but the message."""
    if isinstance(error, LoginRequiredError):
        return LOGINS.get(error.login)
    return REMEDIES.get(error.code)


class ErrorBody(BaseModel):
    """A failure as every inbound adapter reports it: what went wrong, which condition, and what can be done."""

    detail: str
    code: ErrorCode
    remedy: Remedy | None = None

    @classmethod
    def of(cls, error: FrontOfficeError) -> ErrorBody:
        return cls(detail=str(error), code=error.code, remedy=remedy(error))
