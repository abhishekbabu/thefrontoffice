"""ESPN's failures, as the rest of the app sees them."""

from thefrontoffice.domain.errors import PlatformError, PlatformUnavailableError


class ESPNAPIError(PlatformError):
    """An ESPN API call failed.

    Distinct from an empty result: a club nobody has written about this week
    is a valid answer, a failed request is not.
    """

    platform = "ESPN"


class ESPNUnavailableError(PlatformUnavailableError, ESPNAPIError):
    """ESPN is down or not answering."""
