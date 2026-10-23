"""Tests for YahooClient's query building and response parsing.

The client bypasses yahoofantasy's league.players() and builds Yahoo API query
strings by hand, so the query shape and the response walk are both ours to get
right. A fake context stands in for the HTTP layer.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
from thefrontoffice.adapters.outbound.platforms.yahoo.constants import SCOUT_CATEGORIES
from thefrontoffice.domain.errors import (
    TeamNotFoundError,
    YahooAPIError,
    YahooLoginRequiredError,
)


@pytest.fixture(autouse=True)
def _identity_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass yahoofantasy's XML parser.

    FakeContext hands back already-parsed dicts, which is the shape the rest of
    the client works in. Parsing XML is yahoofantasy's job, not ours to retest.
    """
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(mod, "parse_response", lambda raw: raw)


def _player_payload(name: str) -> dict[str, Any]:
    return {"name": {"full": name}, "display_position": "PF", "editorial_team_abbr": "LAL"}


def _response(players: Any) -> dict[str, Any]:
    return {"fantasy_content": {"league": {"players": players}}}


class FakeContext:
    """Stands in for yahoofantasy's Context.

    `make_request` is the only fetch the client still makes through the SDK —
    it caches every response itself now. `_load_or_fetch` survives for the
    scoreboard alone, where `Week.sync` reads the SDK's own store internally
    and pre-warming that key is the only way to force a refresh.
    """

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []
        self.raw_requests: list[str] = []
        self.saved: list[str] = []
        self.persisted: dict[str, Any] = {}
        self._access_token: str | None = "fake-token"
        self.request_threads: set[str] = set()
        self.save_threads: set[str] = set()

    def _get_access_token(self) -> str | None:
        """The SDK's token accessor; a test replaces it to watch refreshes."""
        return self._access_token

    def _load_or_fetch(self, cache_key: str, query: str, **kwargs: Any) -> Any:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.response

    def make_request(self, query: str, **kwargs: Any) -> Any:
        import threading
        import time

        self.request_threads.add(threading.current_thread().name)
        self.raw_requests.append(query)
        if self.error:
            raise self.error
        time.sleep(0.02)  # long enough that serial execution is distinguishable
        return self.response


class RecordingCache(JsonDiskCache):
    """The real cache, kept off disk, recording which thread each write is on.

    Subclassed rather than faked: the client's correctness here is about how it
    uses the store, and the store's own expiry is what the TTLs mean.
    """

    def __init__(self) -> None:
        super().__init__(Path("unused"))
        self.write_threads: set[str] = set()
        self.written: list[str] = []

    def _read(self, key: str) -> Any:  # memory only, never touch disk
        return self._entries.get(key)

    def _write(self, key: str, entry: dict[str, Any]) -> None:  # never touch disk
        return None

    def set(self, key: str, value: Any, now: Any = None) -> None:
        import threading

        self.write_threads.add(threading.current_thread().name)
        self.written.append(key)
        super().set(key, value, now=now)


def _client(
    response: Any = None, error: Exception | None = None, cache: RecordingCache | None = None
) -> tuple[YahooClient, FakeContext]:
    ctx = FakeContext(response, error)
    league = SimpleNamespace(id="123", league_key="nba.l.123", name="My League", ctx=ctx, teams=lambda: [])
    return YahooClient(league, cache=cache or RecordingCache()), ctx


# ── fetch_players ───────────────────────────────────────────────────────


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_scoutable_category() -> None:
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    results = client.fetch_top_by_stat(per_stat=4)
    assert set(results) == set(SCOUT_CATEGORIES.values())
    assert len(ctx.raw_requests) == len(SCOUT_CATEGORIES)
    assert all("count=4" in q for q in ctx.raw_requests)


def test_category_requests_run_concurrently() -> None:
    """Eight independent queries were the dominant latency in a scout run."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    client.fetch_top_by_stat(per_stat=4)
    assert len(ctx.request_threads) > 1, "requests ran on a single thread"


def test_cache_writes_stay_on_one_thread() -> None:
    """Distinct keys are distinct files, so the writes could safely fan out —
    but the cache holds what it has read in memory, and that dict is not
    thread-safe. Only the requests are allowed to fan out."""
    cache = RecordingCache()
    client, _ = _client(_response({"player": [_player_payload("A B")]}), cache=cache)
    client.fetch_top_by_stat(per_stat=4)
    assert len(cache.write_threads) == 1
    assert len(cache.written) == len(SCOUT_CATEGORIES)


def test_cached_categories_are_not_refetched() -> None:
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    client.fetch_top_by_stat(per_stat=4)  # populates the fake cache
    before = len(ctx.raw_requests)
    client.fetch_top_by_stat(per_stat=4)  # second run should be free
    assert len(ctx.raw_requests) == before


def test_unparseable_category_response_raises() -> None:
    """A response we cannot read must not silently become an empty category."""
    client, _ = _client(_response({"player": [_player_payload("A B")]}))

    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    def _explode(raw: object) -> object:
        raise ValueError("malformed xml")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "parse_response", _explode)
        with pytest.raises(YahooAPIError, match="unreadable"):
            client.fetch_top_by_stat(per_stat=4)


def test_a_token_is_refreshed_once_before_the_pool() -> None:
    """Otherwise each worker could trigger its own refresh."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    ctx._access_token = None
    refreshes: list[int] = []

    def _refresh() -> None:
        refreshes.append(1)
        ctx._access_token = "fresh"

    ctx._get_access_token = _refresh
    client.fetch_top_by_stat(per_stat=4)
    assert refreshes == [1]


def test_scoreboard_is_refreshed_on_a_short_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """An hour-old scoreboard would misstate every category margin."""
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = [_matchup()]
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, ctx = _client(_response(""))
    client.league.current_week = 5

    ttls: list[int] = []
    original = ctx._load_or_fetch

    def _record(cache_key: str, query: str, **kwargs: Any) -> Any:
        ttls.append(kwargs.get("persist_ttl", 3600))
        return original(cache_key, query, **kwargs)

    ctx._load_or_fetch = _record
    client.get_matchup(_fake_team("t1"))

    assert ttls == [mod.SCOREBOARD_TTL_SECONDS]
    assert mod.SCOREBOARD_TTL_SECONDS < 3600


def test_a_failed_scoreboard_refresh_falls_back_to_the_persisted_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = [_matchup()]
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, ctx = _client(_response(""))
    client.league.current_week = 5

    def _boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("yahoo down")

    ctx._load_or_fetch = _boom
    info = client.get_matchup(_fake_team("t1"))
    assert info.week_start == "2026-02-09"  # still served from Week.sync


def test_unpersistable_response_is_skipped_not_fatal() -> None:
    """Persisting is best-effort; a save failure must not lose the fetch."""

    class FullDisk(RecordingCache):
        def set(self, key: str, value: Any, now: Any = None) -> None:
            raise OSError("disk full")

    client, _ = _client(_response({"player": [_player_payload("A B")]}), cache=FullDisk())
    results = client.fetch_top_by_stat(per_stat=4)
    assert all(len(v) == 1 for v in results.values())


def test_a_failing_category_raises_rather_than_silently_returning_none() -> None:
    client, _ = _client(error=RuntimeError("yahoo 500"))
    with pytest.raises(RuntimeError, match="yahoo 500"):
        client.fetch_top_by_stat(per_stat=4)


def test_turnovers_are_not_scouted() -> None:
    """Leading the league in turnovers is not a reason to add someone."""
    assert "TO" not in SCOUT_CATEGORIES.values()


# ── get_user_team ───────────────────────────────────────────────────────


def test_the_owned_team_is_returned() -> None:
    mine = SimpleNamespace(name="Mine", is_owned_by_current_login=True)
    theirs = SimpleNamespace(name="Theirs", is_owned_by_current_login=False)
    client, _ = _client()
    client.league.teams = lambda: [theirs, mine]
    assert client.get_user_team() is mine


def test_owning_no_team_raises_with_the_league_name() -> None:
    client, _ = _client()
    client.league.teams = lambda: [SimpleNamespace(name="Theirs", is_owned_by_current_login=False)]
    with pytest.raises(TeamNotFoundError, match="My League"):
        client.get_user_team()


# ── search_players ──────────────────────────────────────────────────────


def test_search_builds_a_league_scoped_query() -> None:
    client, ctx = _client(_response({"player": [_player_payload("LeBron James")]}))
    results = client.search_players("LeBron James")
    assert "league/nba.l.123/players;search=LeBron James" in ctx.raw_requests[0]
    assert [p.name.full for p in results] == ["LeBron James"]


def test_no_matches_is_an_empty_list_not_an_error() -> None:
    """A name that does not exist is a valid answer; a failed request is not."""
    client, _ = _client(_response(""))
    assert client.search_players("Nobody") == []


def test_search_request_failure_raises() -> None:
    client, _ = _client(error=RuntimeError("timeout"))
    with pytest.raises(YahooAPIError, match="Yahoo player search failed"):
        client.search_players("LeBron James")


def test_search_on_an_unexpected_shape_raises() -> None:
    client, _ = _client({"fantasy_content": {}})
    with pytest.raises(YahooAPIError):
        client.search_players("LeBron James")


# ── login ───────────────────────────────────────────────────────────────


def test_existing_token_skips_the_login_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: True))
    monkeypatch.setattr(
        mod.oauth, "authorize", lambda *a, **k: pytest.fail("must not re-authorize with a token cached")
    )

    YahooClient.login()


def test_force_relogins_even_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: True))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mod.oauth, "authorize", lambda *a, **k: calls.append(a))

    YahooClient.login(force=True)

    assert len(calls) == 1


def test_login_passes_credentials_and_the_registered_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """The redirect URI has to be the one registered on the Yahoo app, and the
    same one the token exchange later quotes back."""
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "the-id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "the-secret")
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mod.oauth, "authorize", lambda *a, **k: calls.append(a))

    YahooClient.login()

    assert calls[0] == ("the-id", "the-secret", mod.settings.yahoo_redirect_uri)


def test_missing_credentials_raise_rather_than_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exiting the process is a terminal's idea of failure. Inside a server it
    takes down the request, and no inbound adapter gets to render anything."""
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", None)
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", None)

    with pytest.raises(YahooAPIError, match="must be set"):
        YahooClient.login()


def test_a_failed_handshake_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")

    def _fail(*args: Any, **kwargs: Any) -> None:
        raise YahooLoginRequiredError()

    monkeypatch.setattr(mod.oauth, "authorize", _fail)

    with pytest.raises(YahooLoginRequiredError):
        YahooClient.login()


# ── matchup context ─────────────────────────────────────────────────────


class FakeWeek:
    """Stands in for yahoofantasy's Week."""

    instances: list[FakeWeek] = []

    def __init__(self, ctx: Any, league: Any, week_num: Any) -> None:
        self.matchups = FakeWeek.matchups_to_return
        FakeWeek.instances.append(self)

    matchups_to_return: list[Any] = []

    def sync(self) -> None:
        pass


def _fake_team(team_key: str) -> Any:
    """A duck-typed Team; the client only reads .team_key off it."""
    return SimpleNamespace(team_key=team_key)


def _stat(stat_id: str, value: str) -> Any:
    return SimpleNamespace(stat_id=stat_id, value=value)


def _team_data(points: str, stats: list[Any]) -> Any:
    return SimpleNamespace(
        team_stats=SimpleNamespace(stats=SimpleNamespace(stat=stats)),
        team_points=SimpleNamespace(total=points),
    )


def _matchup(my_key: str = "t1") -> Any:
    mine = SimpleNamespace(team_key=my_key, name="Mine", players=lambda: [])
    theirs = SimpleNamespace(
        team_key="t2",
        name="Theirs",
        players=lambda: [SimpleNamespace(name=SimpleNamespace(full="Star Player"), display_position="PG")],
    )
    return SimpleNamespace(
        team1=mine,
        team2=theirs,
        week_start="2026-02-09",
        week_end="2026-02-15",
        teams=SimpleNamespace(team=[_team_data("50", [_stat("18", "12")]), _team_data("60", [_stat("18", "17")])]),
    )


def _matchup_client(monkeypatch: pytest.MonkeyPatch, matchups: list[Any], current_week: Any = 5) -> Any:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = matchups
    FakeWeek.instances = []
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, _ = _client()
    client.league.current_week = current_week
    return client


# ── translating transport failures ──────────────────────────────────────


def _http(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


def test_a_403_names_the_permission_that_is_actually_missing() -> None:
    """Yahoo says only "not authorized to perform this action", which reads like
    a bad token — and re-authorizing a token that was never the problem is an
    afternoon. The scope on the developer app is the fix."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import translate
    from thefrontoffice.domain.errors import YahooAuthError

    error = translate(_http(403))

    assert isinstance(error, YahooAuthError)
    assert "reviews every application" in str(error)
    assert error.code == "yahoo_not_approved"


def test_any_other_failure_stays_a_generic_api_error() -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import translate
    from thefrontoffice.domain.errors import YahooAPIError, YahooAuthError

    for error in (_http(500), _http(404), requests.exceptions.Timeout()):
        translated = translate(error)
        assert isinstance(translated, YahooAPIError)
        assert not isinstance(translated, YahooAuthError)


def test_an_error_without_a_response_is_translated_rather_than_crashing() -> None:
    """yahoofantasy raises requests' exceptions, and not all carry a response."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import translate
    from thefrontoffice.domain.errors import YahooAPIError

    assert isinstance(translate(ValueError("unparseable")), YahooAPIError)


# ── find_leagues ────────────────────────────────────────────────────────


def _games(games: Any) -> dict[str, Any]:
    return {"fantasy_content": {"users": {"user": {"games": games}}}}


def _league(key: str, name: str) -> dict[str, Any]:
    return {"league_key": {"$": key}, "name": {"$": name}}


def test_leagues_are_looked_up_by_game_code_and_season() -> None:
    """A season newer than the SDK's game-key table is still found: the query
    names the season instead of translating it into a key."""
    ctx = FakeContext(_games({"game": {"leagues": {"league": [_league("466.l.1", "One"), _league("466.l.2", "Two")]}}}))

    leagues = YahooClient.find_leagues(ctx, "nba", 2031, cache=RecordingCache())

    assert ctx.raw_requests == ["users;use_login=1/games;game_codes=nba;seasons=2031/leagues"]
    assert [(league.id, league.name) for league in leagues] == [("466.l.1", "One"), ("466.l.2", "Two")]
    assert all(league.ctx is ctx for league in leagues)


def test_a_single_league_is_not_mistaken_for_a_list() -> None:
    ctx = FakeContext(_games({"game": {"leagues": {"league": _league("466.l.1", "Only")}}}))

    leagues = YahooClient.find_leagues(ctx, "nba", 2026, cache=RecordingCache())

    assert [league.name for league in leagues] == ["Only"]


@pytest.mark.parametrize("games", ["", {"game": {"leagues": ""}}, {"game": {}}], ids=["no-game", "empty", "absent"])
def test_playing_in_no_league_is_an_empty_answer(games: Any) -> None:
    ctx = FakeContext(_games(games))

    assert YahooClient.find_leagues(ctx, "nba", 2026, cache=RecordingCache()) == []


def test_the_league_list_is_served_from_cache_once_fetched() -> None:
    ctx = FakeContext(_games({"game": {"leagues": {"league": _league("466.l.1", "One")}}}))
    cache = RecordingCache()

    YahooClient.find_leagues(ctx, "nba", 2026, cache=cache)
    YahooClient.find_leagues(ctx, "nba", 2026, cache=cache)

    assert len(ctx.raw_requests) == 1


def test_an_unapproved_app_fails_the_league_lookup_by_name() -> None:
    from thefrontoffice.domain.errors import YahooAuthError

    ctx = FakeContext(error=_http(403))

    with pytest.raises(YahooAuthError):
        YahooClient.find_leagues(ctx, "nba", 2026, cache=RecordingCache())


def test_an_unrecognized_league_list_raises() -> None:
    ctx = FakeContext({"fantasy_content": {"error": "?"}})

    with pytest.raises(YahooAPIError, match="unreadable league list"):
        YahooClient.find_leagues(ctx, "nba", 2026, cache=RecordingCache())


# ── authorization is never obtained implicitly ──────────────────────────


def test_a_missing_token_is_reported_not_obtained(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The handshake opens a browser and blocks. A server attempting it would
    wait on a window nobody can see."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.config.settings import settings
    from thefrontoffice.domain.errors import YahooLoginRequiredError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))

    with pytest.raises(YahooLoginRequiredError, match="not authorized on this machine"):
        YahooClient.ensure_authorized()


def test_an_existing_token_satisfies_the_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.config.settings import settings

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    YahooClient.ensure_authorized()  # does not raise


def test_login_without_credentials_raises_rather_than_exiting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A missing credential must raise: sys.exit inside a server kills the request."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.config.settings import settings
    from thefrontoffice.domain.errors import YahooAPIError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))
    monkeypatch.setattr(settings, "yahoo_client_id", None)

    with pytest.raises(YahooAPIError, match="must be set"):
        YahooClient.login()


# ── verifying a token really grants something ───────────────────────────


def test_verify_passes_when_yahoo_answers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod
    from thefrontoffice.config.settings import settings

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))
    monkeypatch.setattr(
        YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=lambda url: "<games/>"))
    )

    YahooClient.verify()  # does not raise
    assert mod  # the module under test, imported for the monkeypatch target


def test_a_token_that_authenticates_but_grants_nothing_is_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The failure this exists for.

    Yahoo answers 403 rather than 401, so the token is genuinely authenticated —
    it simply carries no scope, because the app had no API permissions saved
    when it was issued. Nothing downstream can tell that apart from a
    permissions problem, so it has to be caught at the login.
    """
    from thefrontoffice.config.settings import settings
    from thefrontoffice.domain.errors import YahooAuthError

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    def _refuse(url: str) -> str:
        raise _http(403)

    monkeypatch.setattr(YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=_refuse)))

    with pytest.raises(YahooAuthError, match="reviews every application"):
        YahooClient.verify()


def test_an_unreachable_yahoo_is_not_reported_as_a_permission_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from thefrontoffice.config.settings import settings
    from thefrontoffice.domain.errors import YahooAPIError, YahooAuthError

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    def _down(url: str) -> str:
        raise requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr(YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=_down)))

    with pytest.raises(YahooAPIError) as caught:
        YahooClient.verify()
    assert not isinstance(caught.value, YahooAuthError)


def test_get_context_never_starts_the_browser_handshake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It runs inside a request handler as often as from a terminal."""
    from thefrontoffice.config.settings import settings
    from thefrontoffice.domain.errors import YahooLoginRequiredError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))
    monkeypatch.setattr(
        YahooClient, "login", classmethod(lambda cls, force=False: pytest.fail("login must not be called"))
    )

    with pytest.raises(YahooLoginRequiredError):
        YahooClient.get_context()


def test_conditions_an_adapter_can_offer_to_fix_carry_a_code() -> None:
    """Message text is free to change; a client matching on it would break.

    The remedy differs by adapter — a terminal names a command, the web offers a
    button — so neither belongs in the error and both need to recognize it.
    """
    from thefrontoffice.domain.errors import YahooAuthError, YahooLoginRequiredError

    assert YahooLoginRequiredError().code == "yahoo_login_required"
    assert YahooAuthError().code == "yahoo_not_approved"


def test_no_error_message_names_a_command_or_a_button() -> None:
    """The same text is read in a terminal and in a browser."""
    from thefrontoffice.domain.errors import YahooAuthError, YahooLoginRequiredError

    for error in (YahooLoginRequiredError(), YahooAuthError()):
        assert "just " not in str(error)
        assert "click" not in str(error).lower()
