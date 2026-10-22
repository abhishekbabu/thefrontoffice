"""Tests for the web API.

The routes own transport and error rendering, so that is what is asserted here:
which status a failure becomes, what a client is told, and that a domain model
crosses the wire unchanged. The reports themselves are the engines' tests.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from reports import MOCK_FPL_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.inbound.web import api as web
from thefrontoffice.domain.models import CompetitionContext, PlayerCard
from thefrontoffice.domain.ports import LeagueRef


class FakeProvider:
    """Stands in for any CompetitionProvider."""

    sport = "soccer"

    competition = "premier-league"
    label = "FPL (Fantasy Premier League)"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def list_leagues(self) -> list[LeagueRef]:
        if self.error:
            raise self.error
        return [
            LeagueRef(
                league_id="900",
                name="Work League",
                competition="premier-league",
                detail="3 of 12",
                url="https://fantasy.example/leagues/900",
            )
        ]

    def roster(self, league_id: str) -> list[PlayerCard]:
        if self.error:
            raise self.error
        return [PlayerCard(player_id="10", columns={"Player": "Haaland", "Pos": "FWD", "xPts": "7.4"})]

    def build_context(self, league_id: str) -> CompetitionContext:
        return CompetitionContext(prompt="prompt")

    def build_trade_context(self, league_id: str, proposal: Any) -> CompetitionContext:
        return CompetitionContext(prompt="prompt")


class FakeChat:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[str] = []

    def send_message(self, message: str) -> Any:
        self.sent.append(message)
        if self.error:
            raise self.error
        from types import SimpleNamespace

        return SimpleNamespace(text="Because he has no fixture.")


@pytest.fixture(autouse=True)
def _clear_chats() -> None:
    web._chats.clear()
    web._login = web.LoginState(status="idle")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client whose providers and engines are fakes, so nothing leaves the process."""
    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "scout_engine", lambda p: _Engine())
    monkeypatch.setattr(web, "trade_engine", lambda p: _Engine())
    return TestClient(web.create_app())


class _Engine:
    """Stands in for a wired engine."""

    def start_analysis(self, league_id: str) -> Any:
        return MOCK_FPL_REPORT, FakeChat()

    def evaluate(self, league_id: str, text: str) -> Any:
        return MOCK_NBA_VERDICT, FakeChat()

    judged: Any = None

    def latest(self, league_id: str) -> Any:
        return self.judged


# ── the sport picker ────────────────────────────────────────────────────


def test_sports_include_the_unconfigured_ones(client: TestClient) -> None:
    """Hiding them would silently offer less than the app can do."""
    body = client.get("/api/competitions").json()

    assert {s["competition"] for s in body} == {"nba", "nfl", "premier-league"}
    # And each carries the sport it belongs to, which is what groups them.
    assert {s["sport"] for s in body} == {"basketball", "football", "soccer"}
    assert all("requires" in s for s in body)


def test_a_sport_declares_whether_it_can_trade(client: TestClient) -> None:
    by_sport = {s["competition"]: s for s in client.get("/api/competitions").json()}

    assert by_sport["nfl"]["supports_trades"] is True
    assert by_sport["premier-league"]["supports_trades"] is False


# ── leagues and rosters ─────────────────────────────────────────────────


def test_leagues_are_listed(client: TestClient) -> None:
    body = client.get("/api/premier-league/leagues").json()
    assert body == [
        {
            "league_id": "900",
            "name": "Work League",
            "detail": "3 of 12",
            "url": "https://fantasy.example/leagues/900",
        }
    ]


def test_a_league_carries_the_way_across_to_its_platform(client: TestClient) -> None:
    """Reading a league is this app; the moves are made on the platform, so
    the link has to survive the trip through the wire type — which is its own
    class here and silently drops anything it does not declare."""
    body = client.get("/api/premier-league/leagues").json()

    assert body[0]["url"] == "https://fantasy.example/leagues/900"


def test_a_roster_keeps_the_sports_own_columns(client: TestClient) -> None:
    """The client reads the keys off the data rather than being taught them."""
    body = client.get("/api/premier-league/leagues/900/roster").json()
    assert list(body[0]["columns"]) == ["Player", "Pos", "xPts"]
    assert body[0]["player_id"] == "10"


def test_an_unconfigured_sport_is_a_readable_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """These are conditions the user can act on, not faults in the server."""
    client = TestClient(web.create_app())

    response = client.get("/api/nba/leagues")

    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]


def test_a_platform_failure_reaches_the_client_in_words(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.errors import SleeperAPIError

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider(SleeperAPIError("Sleeper is down")))
    client = TestClient(web.create_app())

    response = client.get("/api/nfl/leagues")

    assert response.status_code == 400
    assert response.json()["detail"] == "Sleeper is down"


# ── reports ─────────────────────────────────────────────────────────────


def test_a_report_crosses_the_wire_as_the_domain_model(client: TestClient) -> None:
    """No second representation to keep in step with ScoutReport."""
    body = client.post("/api/premier-league/leagues/900/scout").json()

    assert body["report"]["situation"] == MOCK_FPL_REPORT.situation
    assert body["report"]["moves"][0]["action"] == "CAPTAIN"
    assert body["chat_id"]


def test_a_verdict_crosses_the_wire_as_the_domain_model(client: TestClient) -> None:
    body = client.post("/api/nfl/leagues/900/trade", json={"text": "Give A, Get B"}).json()

    assert body["verdict"]["verdict"] == MOCK_NBA_VERDICT.verdict
    assert body["verdict"]["gains"] == MOCK_NBA_VERDICT.gains


def test_an_empty_trade_description_is_rejected_before_the_model(client: TestClient) -> None:
    assert client.post("/api/nfl/leagues/900/trade", json={"text": ""}).status_code == 422


def test_a_sport_without_trade_support_is_refused_by_name(client: TestClient) -> None:
    """FPL has no build_trade_context; without this the failure is an AttributeError."""
    response = client.post("/api/premier-league/leagues/900/trade", json={"text": "Give A, Get B"})

    assert response.status_code == 400
    assert "does not support trade evaluation" in response.json()["detail"]


def test_an_unknown_sport_is_a_404(client: TestClient) -> None:
    response = client.post("/api/cricket/leagues/900/trade", json={"text": "Give A, Get B"})
    assert response.status_code == 404


# ── follow-up chat ──────────────────────────────────────────────────────


def test_a_follow_up_reaches_the_chat_the_report_opened(client: TestClient) -> None:
    chat_id = client.post("/api/premier-league/leagues/900/scout").json()["chat_id"]

    body = client.post(f"/api/chat/{chat_id}", json={"message": "Why bench him?"}).json()

    assert body["answer"] == "Because he has no fixture."


def test_an_expired_conversation_says_so(client: TestClient) -> None:
    """Chats live in memory, so a restart loses them. Better said than answered blankly."""
    response = client.post("/api/chat/does-not-exist", json={"message": "Hi"})

    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_a_model_failure_is_a_bad_gateway_not_a_crash(client: TestClient) -> None:
    chat_id = client.post("/api/premier-league/leagues/900/scout").json()["chat_id"]
    web._chats[chat_id] = FakeChat(RuntimeError("quota exhausted"))  # type: ignore[assignment]

    response = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "The model did not answer. Try asking again."


def test_a_follow_up_every_model_refused_says_why(client: TestClient) -> None:
    """A domain error is already a sentence; flattening it to "did not answer"
    would hide that the quota, not the question, is the problem."""
    from thefrontoffice.domain.errors import AIQuotaError

    chat_id = client.post("/api/premier-league/leagues/900/scout").json()["chat_id"]
    error = AIQuotaError("Gemini, Groq")
    web._chats[chat_id] = FakeChat(error)  # type: ignore[assignment]

    response = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    assert response.json()["code"] == error.code


def test_a_league_never_judged_has_no_judgment_to_show(client: TestClient) -> None:
    response = client.get("/api/premier-league/leagues/900/judgment")

    assert response.status_code == 200
    assert response.json() is None


def test_the_last_judgment_is_shown_without_running_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from thefrontoffice.domain.models import Judgment

    engine = _Engine()
    engine.judged = Judgment(report=MOCK_FPL_REPORT, judged_at=datetime.now(timezone.utc), inputs="abc")
    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "scout_engine", lambda p: engine)

    body = TestClient(web.create_app()).get("/api/premier-league/leagues/900/judgment").json()

    assert body["report"]["strategy"] == MOCK_FPL_REPORT.strategy
    assert body["judged_at"]


def test_a_thread_about_one_thing_opens_and_is_asked_through_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[Any] = []

    class _Asker:
        def open(self, league_id: str, subject: Any) -> Any:
            opened.append((league_id, subject.kind, subject.key))
            return FakeChat()

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "ask_engine", lambda p: _Asker())
    client = TestClient(web.create_app())

    chat_id = client.post("/api/premier-league/leagues/900/threads", json={"kind": "task", "key": "swap:a:b"}).json()[
        "chat_id"
    ]
    answer = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"}).json()["answer"]

    assert opened == [("900", "task", "swap:a:b")]
    assert answer


def test_a_thread_about_an_item_since_settled_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.errors import SubjectGoneError

    class _Asker:
        def open(self, league_id: str, subject: Any) -> Any:
            raise SubjectGoneError()

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "ask_engine", lambda p: _Asker())

    response = TestClient(web.create_app()).post(
        "/api/premier-league/leagues/900/threads", json={"kind": "task", "key": "gone"}
    )

    assert response.json()["code"] == SubjectGoneError.code


def test_a_thread_must_name_what_it_is_about(client: TestClient) -> None:
    response = client.post("/api/premier-league/leagues/900/threads", json={"kind": "league", "key": "x"})

    assert response.status_code == 422


def test_an_empty_follow_up_is_rejected(client: TestClient) -> None:
    chat_id = client.post("/api/premier-league/leagues/900/scout").json()["chat_id"]
    assert client.post(f"/api/chat/{chat_id}", json={"message": ""}).status_code == 422


# ── serving the built UI ────────────────────────────────────────────────


def test_the_api_serves_without_a_built_front_end(client: TestClient) -> None:
    """`dist/` is absent during front-end development and in the test suite."""
    assert client.get("/api/competitions").status_code == 200


@pytest.fixture
def built_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client with a front end built, so the catch-all route is mounted."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    monkeypatch.setattr(web, "DIST", dist)
    return TestClient(web.create_app())


def test_a_view_url_returns_the_page_so_a_deep_link_loads(built_client: TestClient) -> None:
    response = built_client.get("/nfl-sleeper/900/team")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_an_unknown_api_path_is_a_404_not_the_page(built_client: TestClient) -> None:
    """Otherwise a renamed or misspelled route answers 200 with HTML, and the
    caller fails on JSON that will not parse instead of on the missing route."""
    response = built_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert "text/html" not in response.headers["content-type"]


# ── settings ────────────────────────────────────────────────────────────


@pytest.fixture
def settings_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client editing a throwaway .env rather than the developer's own."""
    from thefrontoffice.config import env_file

    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=abhibeast\n", encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    monkeypatch.setattr(env_file, "reload_settings", lambda: None)
    return TestClient(web.create_app())


def test_settings_list_every_variable_the_app_reads(settings_client: TestClient) -> None:
    keys = {s["key"] for s in settings_client.get("/api/settings").json()}
    assert {"GOOGLE_API_KEY", "FPL_ENTRY_ID", "SLEEPER_USERNAME"} <= keys


def test_each_setting_declares_the_control_it_needs(settings_client: TestClient) -> None:
    """A page of text boxes invites a typo the validator then rejects on save."""
    kinds = {s["key"]: s["kind"] for s in settings_client.get("/api/settings").json()}

    assert kinds["LOGFIRE_CAPTURE_PROMPTS"] == "boolean"
    assert kinds["FPL_ENTRY_ID"] == "integer"
    assert kinds["YAHOO_MAX_WEEKLY_ADDS"] == "integer"
    assert kinds["LOG_LEVEL"] == "choice"
    assert kinds["SLEEPER_USERNAME"] == "text"


def test_a_fixed_set_of_values_is_offered_rather_than_typed(settings_client: TestClient) -> None:
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "LOG_LEVEL")
    assert entry["choices"] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_a_boolean_reports_its_effective_value_not_the_file_text(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent key and a false one look identical in the file, so the UI would
    otherwise render an unset checkbox for a setting that is genuinely on."""
    from thefrontoffice.config.settings import settings

    monkeypatch.setattr(settings, "logfire_capture_prompts", True)
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "LOGFIRE_CAPTURE_PROMPTS")

    assert entry["value"] == "true"


def test_a_secret_is_never_sent_to_the_client(settings_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """There is nothing the UI can do with the characters of an API key that it
    cannot do with the fact that one is set — and a page that renders them puts
    them in screenshots."""
    from thefrontoffice.config.settings import settings

    monkeypatch.setattr(settings, "gemini_api_key", "super-secret-value")

    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "GOOGLE_API_KEY")

    assert entry["secret"] is True
    assert entry["present"] is True
    assert entry["value"] == ""


def test_a_non_secret_carries_its_value_so_it_can_be_edited(settings_client: TestClient) -> None:
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "SLEEPER_USERNAME")
    assert entry["value"] == "abhibeast"


def test_saving_writes_the_value_and_returns_the_new_state(settings_client: TestClient) -> None:
    body = settings_client.put("/api/settings", json={"values": {"FPL_ENTRY_ID": "4242"}}).json()

    entry = next(s for s in body if s["key"] == "FPL_ENTRY_ID")
    assert entry["value"] == "4242"


def test_a_key_no_setting_reads_is_refused_with_its_name(settings_client: TestClient) -> None:
    response = settings_client.put("/api/settings", json={"values": {"GOOGLE_APIKEY": "oops"}})

    assert response.status_code == 400
    assert "GOOGLE_APIKEY" in response.json()["detail"]


def test_a_shell_variable_is_reported_so_a_futile_edit_is_visible(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FPL_ENTRY_ID", "999")

    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "FPL_ENTRY_ID")

    assert entry["shadowed"] is True


# ── the Yahoo handshake, driven from the UI ─────────────────────────────


def test_a_domain_error_carries_a_code_the_client_can_act_on(client: TestClient) -> None:
    """The message deliberately names no command, so the client needs this to
    know it can offer a button."""
    from thefrontoffice.domain.errors import YahooLoginRequiredError

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(web.data, "build_provider", _raising(YahooLoginRequiredError()))
        body = client.get("/api/nba/leagues").json()

    assert body["code"] == "yahoo_login_required"
    assert "just " not in body["detail"]


def _raising(error: Exception) -> Any:
    """A stand-in that always fails, whatever it is handed."""

    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    return _fail


def test_starting_the_handshake_returns_at_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """It waits on a person and a browser tab; no request can hold that open."""
    monkeypatch.setattr(web.threading, "Thread", _NoopThread)

    body = client.post("/api/yahoo/login").json()

    assert body["status"] == "running"


def test_a_second_start_does_not_open_a_second_browser_tab(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []
    monkeypatch.setattr(web.threading, "Thread", lambda **kw: started.append(kw) or _NoopThread(**kw))

    client.post("/api/yahoo/login")
    client.post("/api/yahoo/login")

    assert len(started) == 1


def test_a_previous_outcome_does_not_leak_into_a_new_attempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale "ok" would report success before anyone had clicked anything."""
    monkeypatch.setattr(web.threading, "Thread", _NoopThread)
    web._login = web.LoginState(status="ok", detail="from last time")

    assert client.post("/api/yahoo/login").json()["status"] == "running"


def test_progress_is_readable_while_it_waits(client: TestClient) -> None:
    web._login = web.LoginState(status="running", detail="waiting")
    assert client.get("/api/yahoo/login").json() == {"status": "running", "detail": "waiting"}


def test_a_failed_handshake_is_reported_in_the_domains_words(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.domain.errors import YahooAuthError

    monkeypatch.setattr(YahooClient, "login", classmethod(lambda cls, force=False: None))
    monkeypatch.setattr(YahooClient, "verify", classmethod(_raising(YahooAuthError())))

    web._run_yahoo_login()

    assert web._login.status == "failed"
    assert "reviews every application" in web._login.detail


def test_success_is_only_reported_once_the_grant_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A login that completes and hands back an inert token is not a success."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient

    calls: list[str] = []
    monkeypatch.setattr(YahooClient, "login", classmethod(lambda cls, force=False: calls.append("login")))
    monkeypatch.setattr(YahooClient, "verify", classmethod(lambda cls: calls.append("verify")))

    web._run_yahoo_login()

    assert calls == ["login", "verify"]
    assert web._login.status == "ok"


class _NoopThread:
    """Starts nothing; the handshake itself is tested directly."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def start(self) -> None: ...


def _with_readiness(monkeypatch: pytest.MonkeyPatch, sport: str, check: Any) -> None:
    """Swap one registered sport's readiness check.

    `CompetitionEntry` is frozen, so the entry is rebuilt and the registry lookup
    pointed at the copy rather than mutated in place.
    """
    import dataclasses

    entries = tuple(
        dataclasses.replace(e, check_ready=check) if e.competition == sport else e for e in web.all_competitions()
    )
    monkeypatch.setattr(web, "all_competitions", lambda: entries)


def test_a_configured_sport_can_still_be_unusable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials being set says nothing about whether the platform answers."""
    from thefrontoffice.domain.errors import YahooLoginRequiredError

    monkeypatch.setattr(web.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(web.settings, "yahoo_client_secret", "secret")
    _with_readiness(monkeypatch, "nba", _raising(YahooLoginRequiredError()))

    nba = next(s for s in client.get("/api/competitions").json() if s["competition"] == "nba")

    assert nba["configured"] is True
    assert nba["ready"] is False
    assert nba["blocked_code"] == "yahoo_login_required"


def test_a_sport_with_nothing_in_the_way_is_ready(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web.settings, "sleeper_username", "abhibeast")

    nfl = next(s for s in client.get("/api/competitions").json() if s["competition"] == "nfl")

    assert (nfl["ready"], nfl["blocked_reason"], nfl["blocked_code"]) == (True, "", "")


def test_an_unconfigured_sport_is_not_probed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Checking readiness on a sport with no credentials would only report the
    credentials, burying the thing the user actually has to set."""
    _with_readiness(monkeypatch, "nba", _raising(AssertionError("must not be probed")))

    nba = next(s for s in client.get("/api/competitions").json() if s["competition"] == "nba")

    assert (nba["configured"], nba["ready"], nba["blocked_reason"]) == (False, False, "")


def test_the_summary_is_served_without_calling_a_model(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point: a page that waits on a model is blank while it waits."""
    from thefrontoffice.domain.models import Side, Spot, Stat, Summary

    monkeypatch.setattr(web, "scout_engine", _raising(AssertionError("must not run the engine")))
    monkeypatch.setattr(
        web.data,
        "build_provider",
        lambda sport: _SummaryProvider(
            Summary(
                headline=[Stat(label="Week", value="4")],
                mine=Side(name="Mine", lineup=[Spot(player="P", detail="d", value="1.0")]),
            )
        ),
    )

    body = client.get("/api/nfl/leagues/L1/summary").json()

    assert body["headline"][0]["label"] == "Week"
    assert body["mine"]["lineup"][0]["player"] == "P"
    assert body["swaps"] == []


class _SummaryProvider(FakeProvider):
    def __init__(self, summary: Any) -> None:
        super().__init__()
        self._summary = summary

    def summary(self, league_id: str) -> Any:
        return self._summary


def test_a_setting_with_a_default_is_not_reported_as_unset(settings_client: TestClient) -> None:
    """An empty field with a default behind it is in force, and showing it as
    unset invites someone to type the value it already has."""
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "LOG_LEVEL")

    assert entry["value"] == ""  # nothing in .env
    assert entry["effective"] == "INFO"  # but this is what runs


def test_a_secrets_effective_value_is_withheld_too(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the placeholder would print the key the field exists to hide."""
    from thefrontoffice.config.settings import settings

    monkeypatch.setattr(settings, "gemini_api_key", "super-secret-value")
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "GOOGLE_API_KEY")

    assert entry["effective"] == ""
    assert entry["present"] is True


def test_every_model_key_saved_in_settings_reaches_the_file_and_turns_analysis_on(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole loop the Settings page exists for: typed in, written to .env,
    never read back, and in effect on the next request with no restart."""
    from thefrontoffice.config import env_file
    from thefrontoffice.config.settings import AppSettings, settings

    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=abhibeast\n", encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
        monkeypatch.setattr(settings, field, None)  # restored after, whatever the reload sets

    def reload_from_tmp() -> None:
        fresh = AppSettings(_env_file=path)  # type: ignore[call-arg]
        for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
            setattr(settings, field, getattr(fresh, field))

    monkeypatch.setattr(env_file, "reload_settings", reload_from_tmp)
    client = TestClient(web.create_app())
    keys = {key: f"{key.lower()}-value" for key in env_file.MODEL_KEYS}

    assert client.get("/api/capabilities").json()["ai"] is False
    response = client.put("/api/settings", json={"values": keys})

    assert response.status_code == 200
    written = path.read_text(encoding="utf-8")
    assert all(f"{key}={value}" in written for key, value in keys.items())
    assert "SLEEPER_USERNAME=abhibeast" in written  # the rest of the file survives
    listed = {s["key"]: s for s in response.json() if s["key"] in keys}
    assert all(s["present"] and s["secret"] for s in listed.values())
    assert not any(value in response.text for value in keys.values())
    assert client.get("/api/capabilities").json()["ai"] is True
