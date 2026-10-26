"""Yahoo's failures, as the rest of the app sees them — including the two its login can fix."""

from thefrontoffice.domain.errors import FrontOfficeError, PlatformError


class YahooAPIError(PlatformError):
    """A Yahoo Fantasy API call failed.

    Distinct from an empty result: `search_players` returning no matches is a
    valid answer, while a failed request is not.
    """

    platform = "Yahoo"


class YahooAuthError(FrontOfficeError):
    """Yahoo authenticated the token and refused the Fantasy Sports API.

    Not a credential problem and not a scope problem, both of which look
    identical from here. Yahoo reviews each application before granting access
    to this API, and an unapproved one gets a valid token that every Fantasy
    endpoint refuses — including endpoints needing no user permission at all,
    which is what distinguishes it from a consent that went wrong.
    """

    code = "yahoo_not_approved"

    def __init__(self) -> None:
        super().__init__(
            "Yahoo refused the Fantasy Sports API for this application. The token is valid — "
            "an invalid one returns 401, not 403 — and even endpoints needing no user "
            "permission are refused, so this is about the app rather than the login. Yahoo "
            "reviews every application before granting access to this API, so creating the app "
            "and ticking Fantasy Sports → Read is necessary but not sufficient. Personal, "
            "single-league use is an accepted category. Authorize again once approved. NFL and "
            "FPL are unaffected."
        )


class YahooLoginRequiredError(FrontOfficeError):
    """No cached Yahoo token, and this process cannot obtain one.

    The handshake opens a browser and waits, which is fine from a terminal and
    impossible inside a request handler — the caller would wait on a window it
    cannot see.
    """

    code = "yahoo_login_required"

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail or "Yahoo is not authorized on this machine yet. Authorizing caches a token and is done once."
        )
