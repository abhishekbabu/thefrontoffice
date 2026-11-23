"""Tests for what the web adapter reads off the registry: `web/data.py`."""

from dataclasses import replace

from support.wiring import FakeCapture, FakeCompetition, entry

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError
from thefrontoffice.application.capabilities import CAPABILITIES
from thefrontoffice.domain.models import CompetitionContext


def _blocked() -> None:
    raise YahooLoginRequiredError()


def _never_probed() -> None:
    raise AssertionError("an unconfigured competition must not be probed")


def test_a_configured_competition_can_still_be_unusable() -> None:
    """Credentials being set says nothing about whether the platform answers."""
    listed = data.competition(entry(FakeCompetition(), check_ready=_blocked))

    assert listed.configured
    assert listed.blocked is not None
    assert (listed.blocked.code, listed.blocked.detail) == (
        YahooLoginRequiredError.code,
        str(YahooLoginRequiredError()),
    )
    assert listed.blocked.remedy is not None and listed.blocked.remedy.action == "authorize"


def test_a_competition_with_nothing_in_the_way_is_not_blocked() -> None:
    assert data.competition(entry(FakeCompetition())).blocked is None


def test_an_unconfigured_competition_is_not_probed() -> None:
    """Checking readiness without credentials would only report the credentials,
    burying the thing the user actually has to set."""
    listed = data.competition(entry(FakeCompetition(), configured=False, check_ready=_never_probed))

    assert listed.blocked is not None
    assert (listed.configured, listed.blocked.code) == (False, "not_configured")
    assert "SLEEPER_USERNAME" in listed.blocked.detail


def test_only_a_competition_with_a_browser_sync_says_it_syncs() -> None:
    """A synced platform's search knows only what the sync carried, which the finder says."""
    plain = entry(FakeCompetition())
    synced = replace(plain, capture=lambda: FakeCapture())

    assert (data.competition(plain).syncs, data.competition(synced).syncs) == (False, True)


class _Wire(FakeCompetition):
    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        raise AssertionError("not asked")


def test_each_flag_says_whether_the_competition_implements_the_port_behind_it() -> None:
    """The flags come from `CAPABILITIES`, so a port added there is offered without listing it here."""
    listed = data.competition(entry(_Wire()))

    flags = {c.flag: getattr(listed, c.flag) for c in CAPABILITIES.values() if c.flag}

    assert flags == {
        "judges_wire": True,
        "plans_weeks": False,
        "browses_weeks": False,
        "finds_trades": False,
        "searches_players": False,
        "refreshes": False,
    }
