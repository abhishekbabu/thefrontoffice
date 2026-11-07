"""Tests for what can be done about a failure: `adapters/inbound/remedies.py`."""

from urllib.parse import urlparse

from thefrontoffice.adapters.inbound import remedies


def test_an_unapproved_application_is_sent_to_yahoos_real_developer_page() -> None:
    """The page once linked a host that does not exist, so the one remedy offered went nowhere."""
    fix = remedies.remedy("access_not_approved")

    assert fix is not None and urlparse(fix.url).netloc == "sports.yahoo.com"
    assert fix.url in fix.command  # the terminal names the same page


def test_a_link_is_the_only_remedy_that_goes_anywhere() -> None:
    assert all(bool(fix.url) == (fix.action == "link") for fix in remedies.REMEDIES.values())


def test_a_condition_with_nothing_to_offer_has_no_remedy() -> None:
    assert remedies.remedy("unknown_competition") is None
