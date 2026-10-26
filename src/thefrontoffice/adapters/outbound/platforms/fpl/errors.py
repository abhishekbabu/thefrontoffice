"""The Fantasy Premier League game's failures, as the rest of the app sees them."""

from thefrontoffice.domain.errors import PlatformError, PlatformUnavailableError


class FPLAPIError(PlatformError):
    """A Fantasy Premier League API call failed.

    Distinct from an empty result: a gameweek with no fixtures for your clubs is
    a valid answer, a failed request is not.
    """

    platform = "FPL"


class FPLUnavailableError(PlatformUnavailableError, FPLAPIError):
    """The Fantasy Premier League game is down or not answering — often while a gameweek is being updated."""
