"""Yahoo's failures, as the rest of the app sees them — including the two its login can fix, the browser sync's and the session cookie's."""

from thefrontoffice.domain.errors import (
    AccessNotApprovedError,
    CaptureRequiredError,
    LoginRequiredError,
    PlatformError,
    PlatformUnavailableError,
    SessionExpiredError,
)


class YahooAPIError(PlatformError):
    """A Yahoo Fantasy API call failed.

    Distinct from an empty result: `search_players` returning no matches is a
    valid answer, while a failed request is not.
    """

    platform = "Yahoo"


class YahooUnavailableError(PlatformUnavailableError, YahooAPIError):
    """Yahoo is down or not answering."""


class YahooAuthError(AccessNotApprovedError):
    """Yahoo authenticated the token and refused the Fantasy Sports API.

    Not a credential problem and not a scope problem, both of which look
    identical from here. Yahoo reviews each application before granting access
    to this API, and an unapproved one gets a valid token that every Fantasy
    endpoint refuses — including endpoints needing no user permission at all,
    which is what distinguishes it from a consent that went wrong.
    """

    login = "yahoo"

    def __init__(self) -> None:
        super().__init__(
            "Yahoo refused this app Fantasy Sports API access (403 with a valid token). Yahoo must "
            "approve the app; ticking Fantasy Sports → Read is not enough. Authorize again once approved."
        )


class YahooLoginRequiredError(LoginRequiredError):
    """No cached Yahoo token, and this process cannot obtain one.

    The handshake opens a browser and waits, which is fine from a terminal and
    impossible inside a request handler — the caller would wait on a window it
    cannot see.
    """

    login = "yahoo"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "Yahoo is not authorized on this machine yet.")


class YahooCaptureMissingError(CaptureRequiredError, YahooAPIError):
    """Yahoo is read from the browser sync, and the last one did not carry what was asked."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "No Yahoo sync yet. Run the sync bookmark from Settings on a Yahoo Fantasy page.")


class YahooSessionExpiredError(SessionExpiredError, YahooAPIError):
    """Yahoo is read with the person's session cookie, and Yahoo refused it: signed out, or timed out."""

    def __init__(self) -> None:
        super().__init__("Yahoo session expired — paste a fresh cookie in Settings.")
