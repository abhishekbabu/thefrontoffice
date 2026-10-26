"""Tests for the web API.

The routes own transport and error rendering, so that is what is asserted here:
which status a failure becomes, what a client is told, and that a domain model
crosses the wire unchanged. The reports themselves are the engines' tests.
"""

from datetime import UTC
from typing import Any

import pytest
from conftest import FakeItemStates
from fastapi.testclient import TestClient
from reports import MOCK_FPL_REPORT

from thefrontoffice.adapters.inbound.web import api as web
from thefrontoffice.application.items import ItemDecisions
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
    decisions = ItemDecisions(FakeItemStates())
    monkeypatch.setattr(web, "item_decisions", lambda: decisions)
    return TestClient(web.create_app())


class _Engine:
    """Stands in for a wired engine."""

    def report(self, league_id: str) -> Any:
        return MOCK_FPL_REPORT

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
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider(SleeperAPIError("Sleeper is down")))
    client = TestClient(web.create_app())

    response = client.get("/api/nfl/leagues")

    assert response.status_code == 400
    assert response.json()["detail"] == "Sleeper is down"


# ── reports ─────────────────────────────────────────────────────────────


def test_a_report_crosses_the_wire_as_the_domain_model(client: TestClient) -> None:
    """No second representation to keep in step with ScoutReport."""
    body = client.post("/api/premier-league/leagues/900/scout").json()

    assert body["situation"] == MOCK_FPL_REPORT.situation
    assert body["moves"][0]["action"] == "CAPTAIN"


def test_free_agents_are_judged_where_the_competition_can(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import PlayerCall

    asked: list[Any] = []

    class _Judge:
        def judge(self, league_id: str, player_ids: list[str]) -> Any:
            asked.append(player_ids)
            return [PlayerCall(player_id=player_ids[0], decision="ADD", drop="B", reason="Lead back now.")]

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "wire_engine", lambda p: _Judge())
    client = TestClient(web.create_app())

    body = client.post("/api/nfl-sleeper/leagues/900/free-agents/judge", json={"player_ids": ["p1", "p2"]}).json()

    assert asked == [["p1", "p2"]]
    assert body[0]["decision"] == "ADD"


def test_the_kept_calls_on_free_agents_are_shown_without_judging(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import PlayerCall

    class _Judge:
        def kept(self, league_id: str, player_ids: list[str]) -> Any:
            return [PlayerCall(player_id=player_ids[0], decision="WATCH", reason="Role growing.", stale=True)]

        def judge(self, league_id: str, player_ids: list[str]) -> Any:
            raise AssertionError("must not ask the model")

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "wire_engine", lambda p: _Judge())

    body = (
        TestClient(web.create_app())
        .post("/api/nfl-sleeper/leagues/900/free-agents/calls", json={"player_ids": ["p1"]})
        .json()
    )

    assert body[0]["decision"] == "WATCH" and body[0]["stale"] is True


def test_judging_free_agents_is_refused_where_it_is_not_offered(client: TestClient) -> None:
    response = client.post("/api/premier-league-fpl/leagues/900/free-agents/judge", json={"player_ids": ["p1"]})

    assert response.status_code == 400


def test_judging_is_bounded_to_a_screen_of_players(client: TestClient) -> None:
    from thefrontoffice.application.wire import MAX_JUDGED

    ids = [f"p{i}" for i in range(MAX_JUDGED + 1)]

    assert client.post("/api/nfl-sleeper/leagues/900/free-agents/judge", json={"player_ids": ids}).status_code == 422


def test_a_competition_says_whether_its_free_agents_can_be_judged(client: TestClient) -> None:
    flags = {c["key"]: c["judges_wire"] for c in client.get("/api/competitions").json()}

    assert flags["nfl-sleeper"] is True and flags["premier-league-fpl"] is False


def test_a_competition_says_whether_its_weeks_and_trades_can_be_planned(client: TestClient) -> None:
    flags = {c["key"]: c["plans_ahead"] for c in client.get("/api/competitions").json()}

    assert flags["nfl-sleeper"] is True and flags["premier-league-fpl"] is False


def test_an_unknown_sport_is_a_404(client: TestClient) -> None:
    response = client.post("/api/cricket/leagues/900/free-agents/judge", json={"player_ids": ["p1"]})
    assert response.status_code == 404


# ── follow-up chat ──────────────────────────────────────────────────────


def _opened(chat: FakeChat | None = None) -> str:
    """A conversation as a thread would have opened it."""
    return web._remember(chat or FakeChat())


def test_a_follow_up_reaches_the_chat_it_names(client: TestClient) -> None:
    chat_id = _opened()

    body = client.post(f"/api/chat/{chat_id}", json={"message": "Why bench him?"}).json()

    assert body["answer"] == "Because he has no fixture."


def test_an_expired_conversation_says_so(client: TestClient) -> None:
    """Chats live in memory, so a restart loses them. Better said than answered blankly."""
    response = client.post("/api/chat/does-not-exist", json={"message": "Hi"})

    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_a_model_failure_is_a_bad_gateway_not_a_crash(client: TestClient) -> None:
    chat_id = _opened(FakeChat(RuntimeError("quota exhausted")))

    response = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "The model did not answer. Try asking again."


def test_a_follow_up_every_model_refused_says_why(client: TestClient) -> None:
    """A domain error is already a sentence; flattening it to "did not answer"
    would hide that the quota, not the question, is the problem."""
    from thefrontoffice.domain.errors import AIQuotaError

    error = AIQuotaError("Gemini, Groq")
    chat_id = _opened(FakeChat(error))

    response = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    assert response.json()["code"] == error.code


def test_a_league_never_judged_has_no_judgment_to_show(client: TestClient) -> None:
    response = client.get("/api/premier-league/leagues/900/judgment")

    assert response.status_code == 200
    assert response.json() is None


def test_the_last_judgment_is_shown_without_running_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime

    from thefrontoffice.domain.models import Remembered

    engine = _Engine()
    engine.judged = Remembered(answer=MOCK_FPL_REPORT, answered_at=datetime.now(UTC), inputs="abc")
    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "scout_engine", lambda p: engine)

    body = TestClient(web.create_app()).get("/api/premier-league/leagues/900/judgment").json()

    assert body["answer"]["strategy"] == MOCK_FPL_REPORT.strategy
    assert body["answered_at"]


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
    assert client.post(f"/api/chat/{_opened()}", json={"message": ""}).status_code == 422


# ── serving the built UI ────────────────────────────────────────────────


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
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

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


def test_a_failed_handshake_is_reported_in_the_domains_words(monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAuthError

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
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

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
        fresh = AppSettings(_env_file=path)
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


# ── deciding about to-do items ──────────────────────────────────────────


def _week_with_one_item() -> Any:
    from thefrontoffice.domain.models import Action, Summary

    item = Action(kind="lineup", urgency="soon", title="Start A over B", reason="+2.5", key="swap:a:b")
    return _SummaryProvider(Summary(actions=[item])), item


def test_a_dismissed_item_comes_back_marked_rather_than_gone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marked, so the page can hide it and still offer it back."""
    provider, item = _week_with_one_item()
    monkeypatch.setattr(web.data, "build_provider", lambda sport: provider)

    kept = client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": item.key, "decision": "dismiss", "fingerprint": item.fingerprint},
    ).json()
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert kept["dismissed_as"] == item.fingerprint
    assert shown["hidden"] == "dismissed"


def test_a_restored_item_is_shown_again(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, item = _week_with_one_item()
    monkeypatch.setattr(web.data, "build_provider", lambda sport: provider)
    client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": item.key, "decision": "dismiss", "fingerprint": item.fingerprint},
    )

    restored = client.post("/api/nfl-sleeper/leagues/L1/items", json={"key": item.key, "decision": "restore"})
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert restored.json() is None
    assert shown["hidden"] is None


def test_a_decision_that_says_too_little_is_rejected(client: TestClient) -> None:
    for incomplete in ({"key": "k", "decision": "dismiss"}, {"key": "k", "decision": "snooze"}):
        assert client.post("/api/nfl-sleeper/leagues/L1/items", json=incomplete).status_code == 422


def test_a_snooze_into_the_past_is_refused_by_name(client: TestClient) -> None:
    from thefrontoffice.domain.errors import ItemDecisionError

    response = client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": "k", "decision": "snooze", "until": "2001-01-01T00:00:00+00:00"},
    )

    assert response.json()["code"] == ItemDecisionError.code


# ── the week, simulated ─────────────────────────────────────────────────


class _ForecastProvider(_SummaryProvider):
    """A provider whose matchup can be simulated, or whose forecast fails."""

    def __init__(self, summary: Any, error: Exception | None = None) -> None:
        super().__init__(summary)
        self.error = error

    def matchup_input(self, league_id: str, candidates: Any = ()) -> Any:
        from thefrontoffice.domain.models import MatchupInput, Outcomes

        if self.error:
            raise self.error
        return MatchupInput(mine=(Outcomes("a", "A", 20.0, (20.0,)),), theirs=(Outcomes("b", "B", 10.0, (10.0,)),))

    def played_matchups(self, league_id: str, week: int) -> Any:
        return []


def test_the_week_carries_its_chance_of_winning(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _ForecastProvider(Summary()))

    body = client.get("/api/nfl-sleeper/leagues/L1/summary").json()

    assert body["forecast"]["win"] == 1.0
    assert "Win chance" in [s["label"] for s in body["headline"]]


def test_a_week_that_cannot_be_simulated_is_still_the_week(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
    from thefrontoffice.domain.models import Stat, Summary

    week = Summary(headline=[Stat(label="Week", value="7")])
    monkeypatch.setattr(web.data, "build_provider", lambda sport: _ForecastProvider(week, SleeperAPIError("down")))

    body = client.get("/api/nfl-sleeper/leagues/L1/summary").json()

    assert body["forecast"] is None and [s["label"] for s in body["headline"]] == ["Week"]


class _WireProvider(_ForecastProvider):
    """A forecastable provider with two free agents, one of whom can start."""

    def free_agents(self, league_id: str, query: Any) -> Any:
        from thefrontoffice.domain.models import PlayerPage

        self.query = query
        return PlayerPage(
            players=[PlayerCard(player_id=pid, columns={"Player": pid}) for pid in ("bench", "starter")], total=2
        )

    def matchup_input(self, league_id: str, candidates: Any = ()) -> Any:
        from thefrontoffice.domain.models import LineupMove, MatchupInput, Outcomes

        if self.error:
            raise self.error
        mine = Outcomes("a", "A", 10.0, (10.0,))
        moves = tuple(
            LineupMove(f"{c}>a", f"Start {c}", ("a",), (Outcomes(c, c, 20.0, (20.0,)),))
            for c in candidates
            if c == "starter"
        )
        return MatchupInput(mine=(mine,), theirs=(Outcomes("b", "B", 15.0, (15.0,)),), moves=moves)


def test_free_agents_carry_what_each_does_to_the_chance(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web.data, "build_provider", lambda sport: _WireProvider(None))

    rows = {p["player_id"]: p for p in client.get("/api/nfl-sleeper/leagues/L1/free-agents").json()["players"]}

    assert rows["starter"]["values"]["Win"] == 1.0  # a sure loss turned a sure win
    assert rows["bench"]["columns"]["Win"] == "—"


def test_sorting_by_the_chance_orders_the_page_from_the_default_ranking(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _WireProvider(None)
    monkeypatch.setattr(web.data, "build_provider", lambda sport: provider)

    body = client.get("/api/nfl-sleeper/leagues/L1/free-agents?sort=Win").json()

    assert provider.query.sort == ""
    assert [p["player_id"] for p in body["players"]] == ["starter", "bench"]


def test_free_agents_that_cannot_be_priced_are_still_the_wire(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _WireProvider(None, SleeperAPIError("down")))

    body = client.get("/api/nfl-sleeper/leagues/L1/free-agents").json()

    assert [p["player_id"] for p in body["players"]] == ["bench", "starter"]
    assert all("Win" not in p["columns"] for p in body["players"])


class _SeasonProvider(_SummaryProvider):
    """A provider whose season can be simulated, or whose simulation fails."""

    def __init__(self, summary: Any, error: Exception | None = None) -> None:
        super().__init__(summary)
        self.error = error

    def season_input(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import SeasonInput, TeamRecord

        if self.error:
            raise self.error
        teams = (TeamRecord("1", "Me", 6, 0, 0, 900.0), TeamRecord("2", "Them", 0, 6, 0, 500.0))
        return SeasonInput(teams=teams, fixtures=(), scoring=(), spots=1, mine="1", week=7)

    def trade_market(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import (
            Fixture,
            SeasonInput,
            TeamRecord,
            TeamWeek,
            TradeMarket,
            TradeOption,
        )

        # Level, with one game left between them: whoever is stronger in it goes through.
        teams = (TeamRecord("1", "Me", 3, 3, 0, 900.0), TeamRecord("2", "Them", 3, 3, 0, 900.0))
        even = (TeamWeek("1", 8, 100.0, 20.0), TeamWeek("2", 8, 100.0, 20.0))
        season = SeasonInput(teams=teams, fixtures=(Fixture(8, "1", "2"),), scoring=even, spots=1, mine="1", week=7)
        rows = (TeamWeek("1", 8, 120.0, 20.0), TeamWeek("2", 8, 100.0, 20.0))
        option = TradeOption("2", ("A (QB)",), ("B (WR)",), points=20.0, their_points=1.0, scoring=rows)
        return TradeMarket(season=season, options=(option,))

    def schedule(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import LeagueSchedule, StandingRow

        return LeagueSchedule(standings=[StandingRow(rank=1, name="Me", team_id="1")])


def test_the_week_carries_the_playoff_chance(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _SeasonProvider(Summary()))

    headline = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["headline"]

    assert {s["label"]: s["value"] for s in headline}["Playoffs"] == "100%"


def test_trades_are_priced_in_playoff_chance(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _SeasonProvider(Summary()))

    [idea] = client.get("/api/nfl-sleeper/leagues/L1/trades").json()

    assert (idea["team"], idea["giving"], idea["receiving"]) == ("Them", ["A (QB)"], ["B (WR)"])
    assert idea["playoffs_change"] > 0


class _OutlookProvider(_SummaryProvider):
    def weeks_ahead(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import WeekAhead

        return [
            WeekAhead(week=8, points=98.0, usual=121.0, missing=["A (bye)"], short=True, fix="Pick up B", gain=12.0)
        ]


def test_the_weeks_ahead_come_back_with_their_fixes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _OutlookProvider(Summary()))

    [week] = client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead").json()

    assert (week["week"], week["short"], week["gain"]) == (8, True, 12.0)


def test_a_competition_that_cannot_look_ahead_has_no_weeks_to_plan(client: TestClient) -> None:
    assert client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead").json() == []


def test_a_competition_with_no_season_to_play_finds_no_trades(client: TestClient) -> None:
    assert client.get("/api/nfl-sleeper/leagues/L1/trades").status_code == 400


def test_the_table_carries_each_teams_playoff_chance(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _SeasonProvider(Summary()))

    [row] = client.get("/api/nfl-sleeper/leagues/L1/schedule").json()["standings"]

    assert row["playoffs"] == "100%"


def test_a_season_that_cannot_be_simulated_is_still_the_league(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
    from thefrontoffice.domain.models import Summary

    monkeypatch.setattr(web.data, "build_provider", lambda sport: _SeasonProvider(Summary(), SleeperAPIError("down")))

    [row] = client.get("/api/nfl-sleeper/leagues/L1/schedule").json()["standings"]
    headline = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["headline"]

    assert row["playoffs"] == "" and headline == []


def test_a_platform_that_is_down_is_a_503_that_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in the request was wrong, so it is not a 400."""
    from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLUnavailableError
    from thefrontoffice.domain.errors import PlatformUnavailableError

    monkeypatch.setattr(
        web.data, "build_provider", lambda sport: FakeProvider(FPLUnavailableError("FPL", "it answered 503"))
    )

    response = client.get("/api/premier-league-fpl/leagues")

    assert response.status_code == 503
    assert response.json()["code"] == PlatformUnavailableError.code
