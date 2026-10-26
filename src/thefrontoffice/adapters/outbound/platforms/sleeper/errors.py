"""Sleeper's failures, as the rest of the app sees them."""

from thefrontoffice.domain.errors import PlatformError, PlatformUnavailableError


class SleeperAPIError(PlatformError):
    """A Sleeper API call failed.

    Distinct from an empty result: a league with no transactions this week is a
    valid answer, a failed request is not.
    """

    platform = "Sleeper"


class SleeperUnavailableError(PlatformUnavailableError, SleeperAPIError):
    """Sleeper is down or not answering."""
