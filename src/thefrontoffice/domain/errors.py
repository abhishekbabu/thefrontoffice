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
    """The configured account does not own a team in this league, or no team has that identifier."""

    def __init__(self, league_name: str) -> None:
        super().__init__(f"Could not identify your team in {league_name}. Are you a manager in this league?")
        self.league_name = league_name


class PlatformError(FrontOfficeError):
    """A call to one of the platforms the app reads failed.

    Distinct from an empty result: a league with no transactions this week is
    a valid answer, a failed request is not. Each platform's adapter has its
    own subclass naming it, so the domain never names a vendor: a caller that
    carries on without a platform catches that adapter's class, and one that
    only renders an error catches this.
    """

    platform: str = "the platform"


class PlatformUnavailableError(PlatformError):
    """A platform is down, overloaded or not answering — nothing the user can fix but wait.

    Told apart from every other failed request because the remedy is different:
    a league that cannot be found is something to correct, a server answering
    503 is something to try again later. Each platform's subclass is also its
    ordinary error's, so whatever already catches that platform's error to
    carry on without it still does.
    """

    code = "platform_unavailable"

    def __init__(self, platform: str, detail: str) -> None:
        super().__init__(
            f"{platform} is not responding right now ({detail}). That is on {platform}'s side, "
            "not this app's; it usually passes within a few minutes."
        )
        self.platform = platform


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


class SubjectGoneError(FrontOfficeError):
    """A question was asked about a to-do item the week no longer holds.

    Not a failure: the item was settled — the swap made, the player back —
    between the page loading and the question. Saying so beats answering
    about a move that is no longer on the table.
    """

    code = "subject_gone"

    def __init__(self) -> None:
        super().__init__("That item is no longer on the list — the week has changed since this page loaded.")


class ItemDecisionError(FrontOfficeError):
    """A decision about a to-do item that cannot be kept as given."""

    code = "item_decision"


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

    def __init__(self, provider: str = "Google", retry_after: float | None = None, detail: str = "") -> None:
        super().__init__(detail or f"The {provider} API quota is exhausted. Analysis will work again once it resets.")
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
