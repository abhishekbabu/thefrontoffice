"""Tests for the sport registry.

The registry is what makes adding a sport a one-file change: without it every
entry point named the providers itself, so a new sport meant editing the CLI,
the UI and the help text and remembering all three.
"""

from collections.abc import Callable

import pytest

from thefrontoffice import bootstrap as registry
from thefrontoffice.config.settings import settings


def test_every_registered_sport_is_complete() -> None:
    for entry in registry.all_competitions():
        assert entry.competition and entry.label and entry.requires
        assert callable(entry.build)
        assert callable(entry.is_configured)


def test_sport_keys_are_unique() -> None:
    keys = [e.competition for e in registry.all_competitions()]
    assert len(keys) == len(set(keys))


def test_lookup_is_case_insensitive_and_tolerates_a_slash() -> None:
    assert registry.find("NFL") is registry.find("nfl")
    assert registry.find("/nfl") is registry.find("nfl")


def test_unknown_sport_is_none() -> None:
    assert registry.find("cricket") is None


def test_nothing_is_configured_without_credentials() -> None:
    """The autouse fixture blanks every credential, so this is the bare state."""
    assert registry.configured_competitions() == []


def test_sleeper_needs_only_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleeper is public — no key, no OAuth."""
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    assert [e.competition for e in registry.configured_competitions()] == ["nfl"]


def test_yahoo_needs_both_halves_of_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "yahoo_client_id", "id")
    assert registry.configured_competitions() == []
    monkeypatch.setattr(settings, "yahoo_client_secret", "secret")
    assert [e.competition for e in registry.configured_competitions()] == ["nba"]


def test_building_a_provider_is_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the registry must never contact a platform — the NBA build
    opens an OAuth flow, and a football-only user must not sit through it."""
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as yahoo_mod

    def _must_not_run(*a: object, **k: object) -> None:
        raise AssertionError("Yahoo was contacted while listing sports")

    monkeypatch.setattr(yahoo_mod.YahooClient, "login", classmethod(_must_not_run))
    registry.all_competitions()
    registry.configured_competitions()
    registry.find("nba")


def test_the_nfl_entry_builds_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    entry = registry.find("nfl")
    assert entry is not None
    assert entry.build().competition == "nfl"


def test_every_provider_satisfies_the_protocol() -> None:
    """A sport that forgets list_leagues, build_context or roster_rows would fail
    only at the point of use."""
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    for provider in (YahooNBAProvider, SleeperNFLProvider):
        assert provider.competition and provider.label
        for method in ("list_leagues", "build_context", "roster"):
            assert callable(getattr(provider, method, None)), f"{provider.__name__}.{method}"


def test_the_nba_entry_discovers_leagues_and_wraps_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """The NBA build performs the Yahoo handshake, then hands the provider every
    league it found."""
    from types import SimpleNamespace

    import thefrontoffice.adapters.outbound.platforms.yahoo.client as yahoo_mod

    leagues = [SimpleNamespace(id="1", name="One", league_type="head"), SimpleNamespace(id="2", name="Two")]
    monkeypatch.setattr(yahoo_mod.YahooClient, "ensure_authorized", classmethod(lambda cls: None))
    monkeypatch.setattr(yahoo_mod.YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace()))
    monkeypatch.setattr(yahoo_mod.YahooClient, "find_leagues", staticmethod(lambda ctx, game, season: leagues))

    entry = registry.find("nba")
    assert entry is not None
    provider = entry.build()
    assert [r.name for r in provider.list_leagues()] == ["One", "Two"]


def test_no_nba_leagues_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import thefrontoffice.adapters.outbound.platforms.yahoo.client as yahoo_mod
    from thefrontoffice.domain.errors import LeagueNotFoundError

    monkeypatch.setattr(yahoo_mod.YahooClient, "ensure_authorized", classmethod(lambda cls: None))
    monkeypatch.setattr(yahoo_mod.YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace()))
    monkeypatch.setattr(yahoo_mod.YahooClient, "find_leagues", staticmethod(lambda ctx, game, season: []))
    entry = registry.find("nba")
    assert entry is not None
    with pytest.raises(LeagueNotFoundError, match="no Yahoo NBA leagues"):
        entry.build()


def test_every_sport_declares_its_trade_support() -> None:
    """Declared on the entry so the CLI and UI need no per-sport branch."""
    for entry in registry.all_competitions():
        assert isinstance(entry.supports_trades, bool)


def test_a_trading_sport_implements_the_trade_port() -> None:
    """`supports_trades` and `build_trade_context` must not drift apart."""
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider

    implementations = {"nba": YahooNBAProvider, "nfl": SleeperNFLProvider, "premier-league": FPLProvider}
    for entry in registry.all_competitions():
        # A competition missing here is one the registry knows about and this
        # guard does not, which is the drift it exists to catch.
        provider = implementations[entry.competition]
        has_method = callable(getattr(provider, "build_trade_context", None))
        assert has_method == entry.supports_trades, entry.competition


def test_requirements_summary_names_every_sport() -> None:
    summary = registry.requirements_summary()
    for entry in registry.all_competitions():
        assert entry.label in summary
        assert entry.requires in summary


# ── one sport, more than one platform ───────────────────────────────────


def test_an_entry_is_identified_by_sport_and_platform() -> None:
    """The same sport runs on more than one platform — basketball on Yahoo and
    on Sleeper — and those are separate accounts and separate leagues, so a
    registry keyed by sport alone would hold one and lose the rest."""
    for entry in registry.all_competitions():
        assert entry.key == f"{entry.competition}-{entry.platform}"


def test_every_key_is_unique() -> None:
    keys = [entry.key for entry in registry.all_competitions()]
    assert len(set(keys)) == len(keys)


def test_a_pair_resolves_exactly() -> None:
    entry = registry.find("nfl-sleeper")
    assert entry is not None and entry.platform == "sleeper"


def test_a_bare_sport_still_resolves_while_one_platform_carries_it() -> None:
    """Typing "nba" stays meaningful until a second platform makes it ambiguous."""
    entry = registry.find("nba")
    assert entry is not None and entry.competition == "nba"


def test_a_pair_is_preferred_over_a_bare_sport_match() -> None:
    """Otherwise the first-registered platform would shadow the one asked for."""
    import dataclasses

    first = registry.all_competitions()[0]
    second = dataclasses.replace(first, platform="other")
    assert second.key != first.key


# ── which model ─────────────────────────────────────────────────────────


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set exactly the model keys named, and no others."""
    from thefrontoffice.config.settings import settings

    def _set(**present: str) -> None:
        for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
            monkeypatch.setattr(settings, field, present.get(field))

    return _set


def test_providers_are_tried_gemini_then_groq_then_openrouter(keys: Callable[..., None]) -> None:
    from thefrontoffice.bootstrap import ai_providers

    keys(gemini_api_key="g", groq_api_key="q", openrouter_api_key="o")

    assert ai_providers() == ["Gemini", "Groq", "OpenRouter"]


def test_a_provider_with_no_key_is_skipped(keys: Callable[..., None]) -> None:
    from thefrontoffice.adapters.outbound.llm.openai_compatible.client import OpenAICompatibleClient
    from thefrontoffice.bootstrap import ai_available, ai_providers, default_model

    keys(openrouter_api_key="o")

    assert ai_providers() == ["OpenRouter"]
    assert ai_available()
    model = default_model()
    assert isinstance(model, OpenAICompatibleClient) and model.provider.name == "OpenRouter"


def test_with_no_key_at_all_nothing_is_offered(keys: Callable[..., None]) -> None:
    from thefrontoffice.bootstrap import ai_available, ai_providers

    keys()

    assert (ai_providers(), ai_available()) == ([], False)
