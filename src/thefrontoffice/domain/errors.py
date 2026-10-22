"""Domain exceptions.

Raised instead of returning `None`, `[]` or an error string, none of which a
caller can tell apart from a real result. The inbound adapters catch
`FrontOfficeError` and render it; nothing else prints.
"""


class FrontOfficeError(Exception):
    """Base class for every expected, user-facing failure.

    The message describes the condition; it never names a command or a button,
    because the same error is read in a terminal and in a browser and the
    remedy differs. `code` is how an inbound adapter recognizes a condition it
    can offer to fix, without matching on message text that is free to change.
    """

    code: str = "error"


class TeamNotFoundError(FrontOfficeError):
    """The current Yahoo login does not own a team in this league."""

    def __init__(self, league_name: str) -> None:
        super().__init__(f"Could not identify your team in {league_name}. Are you a manager in this league?")
        self.league_name = league_name


class YahooAPIError(FrontOfficeError):
    """A Yahoo Fantasy API call failed.

    Distinct from an empty result: `search_players` returning no matches is a
    valid answer, while a failed request is not.
    """


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


class SleeperAPIError(FrontOfficeError):
    """A Sleeper API call failed.

    Distinct from an empty result: a league with no transactions this week is a
    valid answer, a failed request is not.
    """


class ESPNAPIError(FrontOfficeError):
    """An ESPN API call failed.

    Distinct from an empty result: a club nobody has written about this week
    is a valid answer, a failed request is not.
    """


class FPLAPIError(FrontOfficeError):
    """A Fantasy Premier League API call failed.

    Distinct from an empty result: a gameweek with no fixtures for your clubs is
    a valid answer, a failed request is not.
    """


class LeagueNotFoundError(FrontOfficeError):
    """The configured account has no matching league on its platform."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Could not find your league: {detail}")


class PlayerNotFoundError(FrontOfficeError):
    """One or more player names in a trade could not be resolved."""

    def __init__(self, names: list[str]) -> None:
        joined = ", ".join(names)
        super().__init__(
            f"Could not find {'these players' if len(names) > 1 else 'this player'} in the league: {joined}. "
            "Check the spelling, or use the full name as the platform shows it."
        )
        self.names = names


class TradeParseError(FrontOfficeError):
    """The trade description could not be parsed into two sides."""

    def __init__(self, text: str) -> None:
        super().__init__(f"Could not parse the trade from {text!r}. Use the form: 'Give <players>, Get <players>'.")
        self.text = text


class AIUnavailableError(FrontOfficeError):
    """No model is configured, so there is no analysis to give.

    Not a failure so much as a smaller app: everything read from the platforms
    still works, and nothing needing a model should have been offered in the
    first place. A client that reaches this has offered something it should
    have hidden.
    """

    code = "ai_unavailable"

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail
            or "Analysis is unavailable because no model key is set — GOOGLE_API_KEY, GROQ_API_KEY or "
            "OPENROUTER_API_KEY. Add one in Settings to turn it on."
        )


class AIKeyInvalidError(FrontOfficeError):
    """The model refused the key itself.

    Distinct from having no key, which the app hides rather than reports: here
    something was configured and is wrong, which only the person who typed it
    can fix.
    """

    code = "ai_key_invalid"

    def __init__(self, provider: str = "Google", setting: str = "GOOGLE_API_KEY") -> None:
        super().__init__(f"{provider} rejected the API key. Check {setting} in Settings.")
        self.provider = provider


class AIQuotaError(FrontOfficeError):
    """The model is reachable and the key is fine; there is no quota left."""

    code = "ai_quota"

    def __init__(self, provider: str = "Google", retry_after: float | None = None) -> None:
        super().__init__(f"The {provider} API quota is exhausted. Analysis will work again once it resets.")
        self.provider = provider
        self.retry_after = retry_after
        """Seconds until the provider says to try again, where it says at all."""


class AIResponseError(FrontOfficeError):
    """The model was reachable and the call still did not produce a report.

    The vendor's own message is a Python repr of a Google RPC payload, which is
    unreadable and belongs in the log. This carries a sentence instead.
    """

    code = "ai_failed"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or "The model did not return a usable answer. Try again.")
