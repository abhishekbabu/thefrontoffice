"""Tests for the composition root: the registry, and the wiring every entry point is handed.

The registry is what makes adding a competition a one-file change: without it
every entry point named the providers itself, so a new one meant editing the
CLI, the UI and the help text and remembering all three.
"""

from pathlib import Path

import pytest
from support.settings import isolated_settings
from support.wiring import FakeCompetition, entry

from thefrontoffice import bootstrap
from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore
from thefrontoffice.bootstrap import REGISTRY, Registry, nfl_provider
from thefrontoffice.domain.errors import NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.models import Action, CompetitionContext, ItemState, Summary, TradeProposal
from thefrontoffice.domain.ports import (
    CompetitionProvider,
    OutlookProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)

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


def _registry(tmp_path: Path, **values: object) -> Registry:
    """The registry over settings holding exactly `values`, read from nowhere else."""
    return bootstrap.registry(isolated_settings(tmp_path, **values))


def test_nothing_is_configured_without_credentials(tmp_path: Path) -> None:
    assert _registry(tmp_path).configured() == []


def test_sleeper_needs_only_a_username(tmp_path: Path) -> None:
    """Sleeper is public — no key, no OAuth."""
    assert [e.key for e in _registry(tmp_path, sleeper_username="someone").configured()] == ["nfl-sleeper"]


def test_yahoo_needs_both_halves_of_the_credential(tmp_path: Path) -> None:
    assert _registry(tmp_path, yahoo_client_id="id").configured() == []
    both = _registry(tmp_path, yahoo_client_id="id", yahoo_client_secret="secret")
    assert [e.key for e in both.configured()] == ["nba-yahoo"]


def test_a_setting_saved_after_startup_configures_its_competition_at_once(tmp_path: Path) -> None:
    """Settings are read when asked, so a username saved from the UI needs no restart."""
    settings = isolated_settings(tmp_path)
    registry = bootstrap.registry(settings)

    settings.sleeper_username = "someone"

    assert [e.key for e in registry.configured()] == ["nfl-sleeper"]


def test_an_unconfigured_competition_names_what_to_set_rather_than_building(tmp_path: Path) -> None:
    """A football-only user picking NBA must be told what is missing, not dropped into an OAuth flow."""
    with pytest.raises(NotConfiguredError, match="YAHOO_CLIENT_ID"):
        _registry(tmp_path).find("nba").open()


def test_the_nfl_provider_asked_for_directly_names_what_its_entry_requires(tmp_path: Path) -> None:
    """The scripts build it without the registry's gate, and hear the same remedy the gate gives."""
    with pytest.raises(NotConfiguredError, match="SLEEPER_USERNAME"):
        nfl_provider(isolated_settings(tmp_path))


def test_yahoo_is_not_ready_until_a_token_is_cached(tmp_path: Path) -> None:
    """Isolated settings point the token at a file that does not exist."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

    with pytest.raises(YahooLoginRequiredError):
        _registry(tmp_path).find("nba").check_ready()


# ── building a provider ─────────────────────────────────────────────────


def test_the_nfl_entry_builds_its_provider(tmp_path: Path) -> None:
    nfl = _registry(tmp_path, sleeper_username="someone").find("nfl")

    assert isinstance(nfl.open(), nfl.provider())


def test_the_premier_league_entry_builds_its_provider(tmp_path: Path) -> None:
    fpl = _registry(tmp_path, fpl_entry_id=77).find("premier-league")

    assert isinstance(fpl.open(), fpl.provider())


def test_the_nba_entry_builds_its_provider_without_contacting_yahoo(tmp_path: Path) -> None:
    """Building runs on every request; the leagues are found when a call first needs them.

    No token is cached, so the first call that reads Yahoo reports the missing
    login rather than starting one.
    """
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

    nba = _registry(tmp_path).find("nba")

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
    ports = (TradeProvider, WireProvider, OutlookProvider, TradeMarketProvider)
    can = {e.key: tuple(e.can(port) for port in ports) for e in REGISTRY.entries}

    assert can == {
        "nba-yahoo": (True, False, False, False),
        "nfl-sleeper": (True, True, True, True),
        "premier-league-fpl": (False, False, False, False),
    }


class _Trades(FakeCompetition):
    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        raise AssertionError("not asked")


def test_asking_what_a_competition_can_do_builds_nothing() -> None:
    """Building can open an OAuth flow; a client asks before anything is chosen."""
    built: list[int] = []
    trades = entry(_Trades(), built=built)

    assert (trades.can(TradeProvider), trades.can(WireProvider), trades.can(OutlookProvider)) == (True, False, False)
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


def test_providers_are_tried_gemini_then_groq_then_openrouter(tmp_path: Path) -> None:
    settings = isolated_settings(tmp_path, gemini_api_key="g", groq_api_key="q", openrouter_api_key="o")

    assert bootstrap.ai_providers(settings) == ["Gemini", "Groq", "OpenRouter"]


def test_a_provider_with_no_key_is_skipped(tmp_path: Path) -> None:
    assert bootstrap.ai_providers(isolated_settings(tmp_path, openrouter_api_key="o")) == ["OpenRouter"]


def test_with_no_key_at_all_nothing_is_offered(tmp_path: Path) -> None:
    settings = isolated_settings(tmp_path)

    assert (bootstrap.ai_providers(settings), bootstrap.wiring(settings).ai_available()) == ([], False)


def test_a_key_saved_after_startup_counts_at_once(tmp_path: Path) -> None:
    """The model is built per call, so Settings needs no restart."""
    settings = isolated_settings(tmp_path)
    wiring = bootstrap.wiring(settings)

    settings.groq_api_key = "q"

    assert wiring.ai_available()


SWAP = Action(kind="lineup", urgency="now", title="Start A over B", reason="B is out.", key="swap:a:b")


class _OneItem(FakeCompetition):
    def summary(self, league_id: str) -> Summary:
        return Summary(actions=[SWAP])


def test_a_dismissal_kept_under_the_competitions_old_label_still_hides_its_item(tmp_path: Path) -> None:
    """Decisions are keyed by entry now; one made before that is not lost."""
    settings = isolated_settings(tmp_path)
    old = DiskItemStateStore(JsonDiskCache(Path(settings.item_state_dir)))
    old.save("items:NFL (Sleeper):L1", {SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    wiring = bootstrap.wiring(settings)
    week = wiring.week(wiring.registry.find("nfl"), _OneItem()).week("L1")

    assert [a.hidden for a in week.summary.actions or []] == ["dismissed"]
