"""Tests for the sport registry.

The registry is what makes adding a sport a one-file change: without it every
entry point named the providers itself, so a new sport meant editing the CLI,
the UI and the help text and remembering all three.
"""

import typing
from collections.abc import Callable

import pytest

from thefrontoffice import bootstrap as registry
from thefrontoffice.config.settings import settings
from thefrontoffice.domain import ports


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

    # What building the NBA provider calls first: listing and finding must not reach it.
    monkeypatch.setattr(yahoo_mod.YahooClient, "ensure_authorized", classmethod(_must_not_run))
    registry.all_competitions()
    registry.configured_competitions()
    registry.find("nba")


def test_the_nfl_entry_builds_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    entry = registry.find("nfl")
    assert entry is not None
    assert entry.build().competition == "nfl"


def _provider_classes() -> dict[str, type]:
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider

    return {"nba-yahoo": YahooNBAProvider, "nfl-sleeper": SleeperNFLProvider, "premier-league-fpl": FPLProvider}


def _implements(cls: type, port: type) -> bool:
    """Whether a class has every member a port names: checked on the class, so nothing is built."""
    return all(hasattr(cls, member) for member in typing.get_protocol_members(port))


def test_every_registered_provider_implements_the_competition_port() -> None:
    """A competition that forgets a method fails here rather than at the point of use."""
    classes = _provider_classes()

    assert set(classes) == {entry.key for entry in registry.all_competitions()}
    for key, cls in classes.items():
        assert _implements(cls, ports.CompetitionProvider), key


def test_every_capability_a_registry_entry_declares_is_one_its_provider_implements() -> None:
    """The flags are what a client is told before any provider is built; the ports are what the routes check.

    Declared in one place and detected in another, the two could disagree
    silently — a page offering what the server then refuses, or hiding what
    it would do. This holds them together, both ways.
    """
    classes = _provider_classes()
    for entry in registry.all_competitions():
        cls = classes[entry.key]
        assert entry.supports_trades == _implements(cls, ports.TradeProvider), entry.key
        assert entry.judges_wire == _implements(cls, ports.WireProvider), entry.key
        plans = _implements(cls, ports.OutlookProvider) and _implements(cls, ports.TradeMarketProvider)
        assert entry.plans_ahead == plans, entry.key


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


def test_requirements_summary_names_every_sport() -> None:
    summary = registry.requirements_summary()
    for entry in registry.all_competitions():
        assert entry.label in summary
        assert entry.requires in summary


# ── one sport, more than one platform ───────────────────────────────────


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
    from thefrontoffice.bootstrap import ai_available, ai_providers, default_model

    keys(openrouter_api_key="o")

    assert ai_providers() == ["OpenRouter"]
    assert ai_available()
    assert getattr(default_model(), "is_available", False)


def test_a_rested_provider_stays_rested_across_requests() -> None:
    """A model is built per request; a cooldown that forgot itself between
    them would send every report back into the same spent quota."""
    from thefrontoffice.bootstrap import _cooldowns

    try:
        _cooldowns().rest("Groq", 60)

        assert _cooldowns().resting("Groq")
    finally:
        _cooldowns.cache_clear()


def test_with_no_key_at_all_nothing_is_offered(keys: Callable[..., None]) -> None:
    from thefrontoffice.bootstrap import ai_available, ai_providers

    keys()

    assert (ai_providers(), ai_available()) == ([], False)
