"""Tests for the composition root: the registry, and the wiring every entry point is handed.

The registry is what makes adding a competition a one-file change: without it
every entry point named the providers itself, so a new one meant editing the
CLI, the UI and the help text and remembering all three.
"""

from pathlib import Path

import pytest
from support.settings import NOWHERE, isolated_settings
from support.wiring import FakeCompetition, entry

from thefrontoffice import bootstrap
from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore
from thefrontoffice.bootstrap import Registry
from thefrontoffice.domain.errors import NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.models import Action, CompetitionContext, ItemState, Summary, TradeProposal
from thefrontoffice.domain.ports import (
    CompetitionProvider,
    OutlookProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)


def _registry(tmp_path: Path = NOWHERE, **values: object) -> Registry:
    """The registry over settings holding exactly `values`, read from nowhere else; kept under `tmp_path`."""
    return bootstrap.registry(isolated_settings(tmp_path, **values))


# ── finding an entry ────────────────────────────────────────────────────


def test_lookup_is_case_insensitive_and_tolerates_a_slash() -> None:
    registry = _registry()

    assert registry.find("NFL") is registry.find("nfl")
    assert registry.find("/nfl") is registry.find("nfl")


def test_an_unknown_competition_is_an_error_naming_it() -> None:
    with pytest.raises(UnknownCompetitionError, match="cricket"):
        _registry().find("cricket")


def test_every_key_is_unique() -> None:
    keys = [e.key for e in _registry().entries]
    assert len(set(keys)) == len(keys)


def test_a_key_resolves_exactly() -> None:
    assert _registry().find("nfl-sleeper").platform == "sleeper"


def test_a_bare_competition_still_resolves_while_one_platform_carries_it() -> None:
    """Typing "nba" stays meaningful until a second platform makes it ambiguous."""
    assert _registry().find("nba").key == "nba-yahoo"


# ── configuration ───────────────────────────────────────────────────────


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


def test_what_an_entry_asks_for_names_the_variables_its_settings_read() -> None:
    """Said once, by the fields it needs: the message names what a user types, `GOOGLE_API_KEY` style."""
    requires = {e.key: e.requires for e in _registry().entries}

    assert requires == {
        "nba-yahoo": "YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
        "nfl-sleeper": "SLEEPER_USERNAME",
        "premier-league-fpl": "FPL_ENTRY_ID",
    }


def test_a_blank_setting_configures_nothing(tmp_path: Path) -> None:
    """Saved from the UI as an empty field, a username is as good as unset."""
    settings = isolated_settings(tmp_path)
    registry = bootstrap.registry(settings)

    settings.sleeper_username = ""

    assert registry.configured() == []


def test_a_provider_built_without_the_gate_names_what_its_entry_requires(tmp_path: Path) -> None:
    """A builder handed an unconfigured entry says what is missing, as the gate would, rather than build with None."""
    nfl = _registry(tmp_path).find("nfl")

    with pytest.raises(NotConfiguredError, match="SLEEPER_USERNAME"):
        nfl.build(nfl)


def test_only_a_platform_with_a_browser_login_offers_one(tmp_path: Path) -> None:
    """Keyed by the platform its entry names, which is what a login remedy asks for."""
    assert list(_registry(tmp_path).logins()) == ["yahoo"]


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

    provider = nba.build(nba)

    assert isinstance(provider, nba.provider())
    with pytest.raises(YahooLoginRequiredError):
        provider.list_leagues()


# ── what a competition can do ───────────────────────────────────────────


def test_every_registered_provider_implements_the_competition_port() -> None:
    """A competition that forgets a method fails here rather than at the point of use."""
    for e in _registry().entries:
        assert e.can(CompetitionProvider), e.key


def test_what_each_competition_can_do_is_read_off_its_provider() -> None:
    """FPL managers transfer against the market rather than trade; only the NFL simulates its season."""
    ports = (TradeProvider, WireProvider, OutlookProvider, TradeMarketProvider)
    can = {e.key: tuple(e.can(port) for port in ports) for e in _registry().entries}

    assert can == {
        "nba-yahoo": (True, False, False, False),
        "nfl-sleeper": (True, True, True, True),
        "premier-league-fpl": (False, False, False, False),
    }


class _Trades(FakeCompetition):
    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        raise AssertionError("not asked")


def test_asking_what_a_competition_can_do_builds_nothing() -> None:
    """A client asks before anything is chosen, and building one reads its settings and opens its caches."""
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
    old = DiskItemStateStore(DiskCache(Path(settings.item_state_dir)))
    old.save("items:NFL (Sleeper):L1", {SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    wiring = bootstrap.wiring(settings)
    week = wiring.week(wiring.registry.find("nfl"), _OneItem()).week("L1")

    assert [a.mark.hidden for a in week.summary.actions or []] == ["dismissed"]


# ── Yahoo from the browser sync ─────────────────────────────────────────


def test_read_from_the_browser_yahoo_needs_no_app_credentials(tmp_path: Path) -> None:
    nba = _registry(tmp_path, yahoo_source="browser").find("nba")

    assert nba.is_configured()
    assert nba.requires == ""


def test_switching_to_the_browser_sync_counts_without_a_restart(tmp_path: Path) -> None:
    settings = isolated_settings(tmp_path)
    nba = bootstrap.registry(settings).find("nba")

    settings.yahoo_source = "browser"

    assert nba.is_configured()


def test_read_from_the_browser_yahoo_is_not_ready_until_a_sync_has_run(tmp_path: Path) -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooCaptureMissingError

    with pytest.raises(YahooCaptureMissingError):
        _registry(tmp_path, yahoo_source="browser").find("nba").check_ready()


def test_read_from_the_browser_the_nba_provider_reads_the_capture_not_yahoo(tmp_path: Path) -> None:
    """No token is cached, so reaching for the OAuth login would raise that instead."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooCaptureMissingError

    nba = _registry(tmp_path, yahoo_source="browser").find("nba")

    with pytest.raises(YahooCaptureMissingError):
        nba.open().list_leagues()


def test_only_yahoo_offers_a_browser_sync_and_it_plans_its_league_list(tmp_path: Path) -> None:
    captures = _registry(tmp_path).captures()

    assert list(captures) == ["yahoo"]
    [step] = captures["yahoo"]().plan([]).steps
    assert "game_codes=nba" in step.path


# ── Yahoo with the session cookie ───────────────────────────────────────

COOKIE = "A1=session-cookie"


def test_read_with_the_session_yahoo_needs_the_cookie_and_no_app_credentials(tmp_path: Path) -> None:
    without = _registry(tmp_path, yahoo_source="session").find("nba")
    with_cookie = _registry(tmp_path, yahoo_source="session", yahoo_session_cookie=COOKIE).find("nba")

    assert not without.is_configured()
    assert without.requires == "YAHOO_SESSION_COOKIE"
    assert with_cookie.is_configured()


def test_read_with_the_session_yahoo_is_not_ready_once_yahoo_refused_that_cookie(tmp_path: Path) -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooSessionExpiredError
    from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionState

    settings = isolated_settings(tmp_path, yahoo_source="session", yahoo_session_cookie=COOKIE)
    nba = bootstrap.registry(settings).find("nba")
    nba.check_ready()
    state = SessionState(DiskCache(Path(settings.yahoo_cache_dir)), COOKIE)
    state.refused()
    state.record()

    with pytest.raises(YahooSessionExpiredError):
        nba.check_ready()
    assert nba.blocker() is not None
    settings.yahoo_session_cookie = "A1=fresh"
    nba.check_ready()


def test_read_with_the_session_the_nba_provider_reads_what_is_kept_under_yahoos_paths(tmp_path: Path) -> None:
    """No token is cached and no frontend answers, so either would fail; the kept league list answers."""
    from support.yahoo import league_xml, leagues_xml

    settings = isolated_settings(tmp_path, yahoo_source="session", yahoo_session_cookie=COOKIE)
    registry = bootstrap.registry(settings)
    [step] = registry.captures()["yahoo"]().plan([]).steps
    DiskCache(Path(settings.yahoo_cache_dir)).set(step.path, leagues_xml(league_xml("466.l.9", "Kept")))

    leagues = registry.find("nba").open().list_leagues()

    assert [league.name for league in leagues] == ["Kept"]


def test_read_with_the_session_the_sync_status_reports_the_session(tmp_path: Path) -> None:
    session = _registry(tmp_path, yahoo_source="session", yahoo_session_cookie=COOKIE).captures()["yahoo"]()
    browser = _registry(tmp_path, yahoo_source="browser").captures()["yahoo"]()

    assert session.status().session is not None
    assert browser.status().session is None


# ── the request budget ──────────────────────────────────────────────────


def test_every_reader_of_one_host_shares_one_pace_and_each_cookie_its_own_breaker() -> None:
    """Providers are built per request, so a budget held by any one of them would pace nothing."""
    from thefrontoffice.adapters.outbound.platforms.yahoo import paths

    first, again = (
        bootstrap._yahoo_budget_for(paths.FRONTEND, COOKIE),
        bootstrap._yahoo_budget_for(paths.FRONTEND, COOKIE),
    )
    fresh = bootstrap._yahoo_budget_for(paths.FRONTEND, "A1=fresh")
    api = bootstrap._yahoo_budget_for(paths.API, COOKIE)

    assert first.throttle is again.throttle is fresh.throttle
    assert first.breaker is again.breaker
    assert fresh.breaker is not first.breaker
    assert api.throttle is not first.throttle


def test_background_refreshes_for_one_cache_share_one_worker(tmp_path: Path) -> None:
    assert bootstrap._yahoo_refresher(str(tmp_path)) is bootstrap._yahoo_refresher(str(tmp_path))


def test_an_nba_scoreboard_is_live_only_in_game_hours_on_a_day_with_games() -> None:
    from dataclasses import replace
    from datetime import UTC, datetime

    def live(utc_hour: int, games_on: bool) -> bool:
        moment = datetime(2026, 11, 19, utc_hour, tzinfo=UTC)
        return replace(bootstrap._nba_pace(lambda _: games_on), clock=lambda: moment).live()

    assert live(3, games_on=True)  # 19:00 Pacific
    assert not live(3, games_on=False)
    assert not live(12, games_on=True)  # 04:00 Pacific
