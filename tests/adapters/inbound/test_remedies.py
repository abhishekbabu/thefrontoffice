"""Tests for what can be done about a failure: `adapters/inbound/remedies.py`."""

from urllib.parse import urlparse

from thefrontoffice.adapters.inbound import remedies
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAuthError, YahooLoginRequiredError
from thefrontoffice.domain.errors import LoginRequiredError, UnknownCompetitionError


def test_an_unapproved_application_is_sent_to_yahoos_real_developer_page() -> None:
    """The page once linked a host that does not exist, so the one remedy offered went nowhere."""
    fix = remedies.remedy(YahooAuthError())

    assert fix is not None and urlparse(fix.url).netloc == "sports.yahoo.com"
    assert fix.url in fix.command  # the terminal names the same page


def test_a_link_is_the_only_remedy_that_goes_anywhere() -> None:
    assert all(bool(fix.url) == (fix.action == "link") for fix in remedies.REMEDIES.values())


def test_a_condition_with_nothing_to_offer_has_no_remedy() -> None:
    assert remedies.remedy(UnknownCompetitionError("cricket")) is None


def test_a_missing_login_offers_the_login_of_the_platform_that_needs_it() -> None:
    fix = remedies.remedy(YahooLoginRequiredError())

    assert fix is not None and (fix.action, fix.platform) == ("authorize", "yahoo")


def test_a_platform_with_no_login_to_offer_has_no_remedy() -> None:
    """Better no button than one that starts some other platform's handshake."""

    class Elsewhere(LoginRequiredError):
        platform = "elsewhere"

    assert remedies.remedy(Elsewhere()) is None


def test_every_condition_fixed_in_settings_tells_a_terminal_what_to_do_instead() -> None:
    """A terminal has no Settings page, and the domain's message no longer names one."""
    assert all(fix.command for fix in remedies.REMEDIES.values() if fix.action == "settings")
