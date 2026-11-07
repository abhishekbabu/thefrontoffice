"""Tests for the composition root: the registry, and the wiring every entry point is handed.

The registry is what makes adding a competition a one-file change: without it
every entry point named the providers itself, so a new one meant editing the
CLI, the UI and the help text and remembering all three.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from support.wiring import FakeCompetition, entry

from thefrontoffice import bootstrap
from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore
from thefrontoffice.bootstrap import REGISTRY
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.models import Action, ItemState, Summary
from thefrontoffice.domain.ports import CompetitionProvider, TradeProvider, WireProvider

# ── finding an entry ────────────────────────────────────────────────────


def test_lookup_is_case_insensitive_and_tolerates_a_slash() -> None:
    assert REGISTRY.find("NFL") is REGISTRY.find("nfl")
    assert REGISTRY.find("/nfl") is REGISTRY.find("nfl")


def test_an_unknown_competition_is_an_error_naming_it() -> None:
    with pytest.raises(UnknownCompetitionError, match="cricket"):
        REGISTRY.find("cricket")


def test_every_key_is_unique() -> None:
    keys = [e.key for e in REGISTRY.entries]
    assert len(set(keys)) == len(keys)


def test_a_key_resolves_exactly() -> None:
    assert REGISTRY.find("nfl-sleeper").platform == "sleeper"


def test_a_bare_competition_still_resolves_while_one_platform_carries_it() -> None:
    """Typing "nba" stays meaningful until a second platform makes it ambiguous."""
    assert REGISTRY.find("nba").key == "nba-yahoo"


# ── configuration ───────────────────────────────────────────────────────


def test_nothing_is_configured_without_credentials() -> None:
    """The autouse fixture blanks every credential, so this is the bare state."""
    assert REGISTRY.configured() == []


def test_sleeper_needs_only_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleeper is public — no key, no OAuth."""
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    assert [e.key for e in REGISTRY.configured()] == ["nfl-sleeper"]


def test_yahoo_needs_both_halves_of_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "yahoo_client_id", "id")
    assert REGISTRY.configured() == []
    monkeypatch.setattr(settings, "yahoo_client_secret", "secret")
    assert [e.key for e in REGISTRY.configured()] == ["nba-yahoo"]


def test_an_unconfigured_competition_names_what_to_set_rather_than_building() -> None:
    """A football-only user picking NBA must be told what is missing, not dropped into an OAuth flow."""
    with pytest.raises(NotConfiguredError, match="YAHOO_CLIENT_ID"):
        REGISTRY.find("nba").open()


def test_yahoo_is_not_ready_until_a_token_is_cached() -> None:
    """The autouse fixture points the token at a file that does not exist."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

    with pytest.raises(YahooLoginRequiredError):
        REGISTRY.find("nba").check_ready()


# ── building a provider ─────────────────────────────────────────────────


def test_the_nfl_entry_builds_its_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    nfl = REGISTRY.find("nfl")

    assert isinstance(nfl.open(), nfl.provider())


def test_the_premier_league_entry_builds_its_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fpl_entry_id", 77)
    fpl = REGISTRY.find("premier-league")

    assert isinstance(fpl.open(), fpl.provider())


def test_the_nba_entry_builds_its_provider_without_contacting_yahoo() -> None:
    """Building runs on every request; the leagues are found when a call first needs them.

    The autouse fixture leaves no token cached, so the first call that reads
    Yahoo reports the missing login rather than starting one.
    """
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

    nba = REGISTRY.find("nba")

    provider = nba.build()

    assert isinstance(provider, nba.provider())
    with pytest.raises(YahooLoginRequiredError):
        provider.list_leagues()


# ── what a competition can do ───────────────────────────────────────────


def test_every_registered_provider_implements_the_competition_port() -> None:
    """A competition that forgets a method fails here rather than at the point of use."""
    for e in REGISTRY.entries:
        assert e.can(CompetitionProvider), e.key


def test_what_each_competition_can_do_is_read_off_its_provider() -> None:
    """FPL managers transfer against the market rather than trade; only the NFL simulates its season."""
    can = {e.key: (e.supports_trades, e.judges_wire, e.plans_ahead) for e in REGISTRY.entries}

    assert can == {
        "nba-yahoo": (True, False, False),
        "nfl-sleeper": (True, True, True),
        "premier-league-fpl": (False, False, False),
    }


class _Trades(FakeCompetition):
    def build_trade_context(self, league_id: str, proposal: object) -> object:
        raise AssertionError("not asked")


def test_asking_what_a_competition_can_do_builds_nothing() -> None:
    """Building can open an OAuth flow; a client asks before anything is chosen."""
    built: list[int] = []
    trades = entry(_Trades(), built=built)

    assert (trades.supports_trades, trades.judges_wire, trades.plans_ahead) == (True, False, False)
    assert built == []


def test_a_capability_it_lacks_is_refused_by_name_without_building() -> None:
    built: list[int] = []
    plain = entry(FakeCompetition(), label="Plain", built=built)

    with pytest.raises(UnsupportedError, match="Plain"):
        plain.open_as(WireProvider, "judging free agents")
    assert built == []


def test_a_capability_it_has_comes_back_as_that_port() -> None:
    provider = _Trades()

    assert entry(provider).open_as(TradeProvider, "trade evaluation") is provider


# ── the wiring ──────────────────────────────────────────────────────────


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set exactly the model keys named, and no others."""

    def _set(**present: str) -> None:
        for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
            monkeypatch.setattr(settings, field, present.get(field))

    return _set


def test_providers_are_tried_gemini_then_groq_then_openrouter(keys: Callable[..., None]) -> None:
    keys(gemini_api_key="g", groq_api_key="q", openrouter_api_key="o")

    assert bootstrap.ai_providers() == ["Gemini", "Groq", "OpenRouter"]


def test_a_provider_with_no_key_is_skipped(keys: Callable[..., None]) -> None:
    keys(openrouter_api_key="o")

    assert bootstrap.ai_providers() == ["OpenRouter"]


def test_with_no_key_at_all_nothing_is_offered(keys: Callable[..., None]) -> None:
    keys()

    assert (bootstrap.ai_providers(), bootstrap.wiring().ai_available()) == ([], False)


def test_a_key_saved_after_startup_counts_at_once(keys: Callable[..., None]) -> None:
    """The model is built per call, so Settings needs no restart."""
    wiring = bootstrap.wiring()
    keys(groq_api_key="q")

    assert wiring.ai_available()


SWAP = Action(kind="lineup", urgency="now", title="Start A over B", reason="B is out.", key="swap:a:b")


class _OneItem(FakeCompetition):
    def summary(self, league_id: str) -> Summary:
        return Summary(actions=[SWAP])


def test_a_dismissal_kept_under_the_competitions_old_label_still_hides_its_item() -> None:
    """Decisions are keyed by entry now; one made before that is not lost."""
    old = DiskItemStateStore(JsonDiskCache(Path(settings.item_state_dir)))
    old.save("items:NFL (Sleeper):L1", {SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    week = bootstrap.wiring().week(REGISTRY.find("nfl"), _OneItem()).week("L1")

    assert [a.hidden for a in week.summary.actions or []] == ["dismissed"]
