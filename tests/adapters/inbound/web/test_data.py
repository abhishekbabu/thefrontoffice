"""Tests for what the web adapter reads off the registry: `web/data.py`."""

from support.wiring import FakeCompetition, entry

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError


def _blocked() -> None:
    raise YahooLoginRequiredError()


def _never_probed() -> None:
    raise AssertionError("an unconfigured competition must not be probed")


def test_a_configured_competition_can_still_be_unusable() -> None:
    """Credentials being set says nothing about whether the platform answers."""
    listed = data.competition(entry(FakeCompetition(), check_ready=_blocked))

    assert (listed.configured, listed.ready) == (True, False)
    assert listed.blocked_code == YahooLoginRequiredError.code
    assert listed.blocked_reason == str(YahooLoginRequiredError())
    assert listed.blocked_remedy is not None and listed.blocked_remedy.action == "authorize"


def test_a_competition_with_nothing_in_the_way_is_ready() -> None:
    listed = data.competition(entry(FakeCompetition()))

    assert (listed.ready, listed.blocked_reason, listed.blocked_code, listed.blocked_remedy) == (True, "", None, None)


def test_an_unconfigured_competition_is_not_probed() -> None:
    """Checking readiness without credentials would only report the credentials,
    burying the thing the user actually has to set."""
    listed = data.competition(entry(FakeCompetition(), configured=False, check_ready=_never_probed))

    assert (listed.configured, listed.ready, listed.blocked_code) == (False, False, "not_configured")
    assert "SLEEPER_USERNAME" in listed.blocked_reason


def test_a_competition_is_listed_under_its_key_with_what_it_needs() -> None:
    listed = data.competition(entry(FakeCompetition(), requires="SLEEPER_USERNAME"))

    assert (listed.key, listed.requires) == ("nfl-sleeper", "SLEEPER_USERNAME")
