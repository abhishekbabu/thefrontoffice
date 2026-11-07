"""Tests for the web API.

The routes own transport and error rendering, so that is what is asserted here:
which status a failure becomes, what a client is told, and that a domain model
crosses the wire unchanged. The reports themselves are the engines' tests.

Every app is built over a wiring of fakes from `support/wiring.py`: nothing is
patched, and nothing leaves the process.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.ai import FakeAI, FakeChat
from support.reports import MOCK_FPL_REPORT
from support.stores import FakeAnswers
from support.wiring import FakeCompetition, FakeLogin, entry
from support.wiring import wiring as fake_wiring

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.web import api as web
from thefrontoffice.application.formats import CallAnswer, WireAnswer
from thefrontoffice.application.scouting import scout_scope
from thefrontoffice.bootstrap import REGISTRY
from thefrontoffice.domain.models import Action, CompetitionContext, PlayerCall, PlayerCard, Remembered
from thefrontoffice.domain.ports import LeagueRef

ITEM = Action(kind="lineup", urgency="soon", title="Start A over B", reason="+2.5", key="swap:a:b")


class FakeProvider(FakeCompetition):
    """A competition with one league and one player, and a trade path; or one whose every read fails."""

    leagues = (
        LeagueRef(league_id="900", name="Work League", detail="3 of 12", url="https://fantasy.example/leagues/900"),
    )

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def list_leagues(self) -> list[LeagueRef]:
        if self.error:
            raise self.error
        return super().list_leagues()

    def roster(self, league_id: str) -> list[PlayerCard]:
        if self.error:
            raise self.error
        return [PlayerCard(player_id="10", columns={"Player": "Haaland", "Pos": "FWD", "xPts": "7.4"})]

    def build_context(self, league_id: str) -> CompetitionContext:
        return CompetitionContext(prompt="prompt", tasks=[ITEM])

    def build_trade_context(self, league_id: str, proposal: Any) -> CompetitionContext:
        return CompetitionContext(prompt="prompt")


class _Wire(FakeProvider):
    """A competition whose free agents can be judged."""

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        return CompetitionContext(prompt="\n".join(player_ids), targets={pid: pid for pid in player_ids})


def _client(provider: FakeCompetition | None = None, **wiring: Any) -> TestClient:
    """An app whose every registered competition is served by `provider`."""
    served = provider or FakeProvider()
    entries = [
        entry(
            served,
            competition=e.competition,
            platform=e.platform,
            label=e.label,
            name=e.name,
            sport=e.sport,
            requires=e.requires,
        )
        for e in REGISTRY.entries
    ]
    return TestClient(web.create_app(fake_wiring(*entries, **wiring)))


@pytest.fixture
def client() -> TestClient:
    return _client()


# ── the competition picker ──────────────────────────────────────────────


def test_competitions_include_the_unconfigured_ones() -> None:
    """Hiding them would silently offer less than the app can do."""
    body = TestClient(web.create_app(fake_wiring(registry=REGISTRY.entries))).get("/api/competitions").json()

    assert {s["key"] for s in body} == {"nba-yahoo", "nfl-sleeper", "premier-league-fpl"}
    assert {s["sport"] for s in body} == {"basketball", "football", "soccer"}
    assert not any(s["configured"] for s in body)


def test_a_competition_says_what_it_can_do() -> None:
    body = TestClient(web.create_app(fake_wiring(registry=REGISTRY.entries))).get("/api/competitions").json()
    flags = {c["key"]: (c["judges_wire"], c["plans_ahead"]) for c in body}

    assert flags["nfl-sleeper"] == (True, True) and flags["premier-league-fpl"] == (False, False)


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


def test_a_roster_keeps_the_competitions_own_columns(client: TestClient) -> None:
    """The client reads the keys off the data rather than being taught them."""
    body = client.get("/api/premier-league/leagues/900/roster").json()
    assert list(body[0]["columns"]) == ["Player", "Pos", "xPts"]
    assert body[0]["player_id"] == "10"


def test_an_unconfigured_competition_is_a_readable_400() -> None:
    """These are conditions the user can act on, not faults in the server."""
    client = TestClient(web.create_app(fake_wiring(registry=REGISTRY.entries)))

    response = client.get("/api/nba-yahoo/leagues")

    assert response.status_code == 400
    assert "YAHOO_CLIENT_ID" in response.json()["detail"]
    assert response.json()["code"] == "not_configured"


def test_an_unknown_competition_is_a_404(client: TestClient) -> None:
    response = client.get("/api/cricket/leagues")

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_competition"


def test_a_platform_failure_reaches_the_client_in_words() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    error = SleeperAPIError("Sleeper is down")

    response = _client(FakeProvider(error)).get("/api/nfl/leagues")

    assert response.status_code == 400
    assert response.json() == {"detail": str(error), "code": error.code, "remedy": None}


def test_a_domain_error_carries_a_code_the_client_can_act_on() -> None:
    """The message deliberately names no command, so the client needs this to know it can offer a button."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

    body = _client(FakeProvider(YahooLoginRequiredError())).get("/api/nba/leagues").json()

    assert body["code"] == YahooLoginRequiredError.code
    assert body["remedy"]["action"] == "authorize"


def test_the_app_says_its_limits_rather_than_leaving_the_page_to_restate_them(client: TestClient) -> None:
    from thefrontoffice.application.season import MIN_TRADE_CHANGE
    from thefrontoffice.application.wire import MAX_JUDGED

    limits = client.get("/api/capabilities").json()["limits"]

    assert limits == {"judged": MAX_JUDGED, "trade_change": MIN_TRADE_CHANGE}


# ── reports ─────────────────────────────────────────────────────────────


def test_a_report_crosses_the_wire_as_the_domain_model() -> None:
    """No second representation to keep in step with ScoutReport."""
    body = _client(ai=FakeAI(report=MOCK_FPL_REPORT)).post("/api/premier-league/leagues/900/scout").json()

    assert body["situation"] == MOCK_FPL_REPORT.situation
    assert body["moves"][0]["action"] == "CAPTAIN"


def test_a_league_never_judged_has_no_judgment_to_show(client: TestClient) -> None:
    response = client.get("/api/premier-league/leagues/900/judgment")

    assert response.status_code == 200
    assert response.json() is None


def test_the_last_judgment_is_shown_without_running_the_model() -> None:
    answers = FakeAnswers()
    answers.save(
        scout_scope("premier-league-fpl", "900"),
        Remembered(answer=MOCK_FPL_REPORT, answered_at=datetime.now(UTC), inputs="abc"),
    )
    ai = FakeAI()

    body = _client(ai=ai, answers=answers).get("/api/premier-league/leagues/900/judgment").json()

    assert body["answer"]["strategy"] == MOCK_FPL_REPORT.strategy
    assert body["answered_at"]
    assert ai.prompts == []


def test_the_summary_is_served_without_calling_a_model() -> None:
    """The whole point: a page that waits on a model is blank while it waits."""
    from thefrontoffice.domain.models import Side, Spot, Stat, Summary

    ai = FakeAI()
    week = Summary(
        headline=[Stat(label="Week", value="4")],
        mine=Side(name="Mine", lineup=[Spot(player="P", detail="d", value="1.0")]),
    )

    body = _client(_SummaryProvider(week), ai=ai).get("/api/nfl/leagues/L1/summary").json()

    assert body["headline"][0]["label"] == "Week"
    assert body["mine"]["lineup"][0]["player"] == "P"
    assert body["swaps"] == []
    assert ai.prompts == []


# ── free agents ─────────────────────────────────────────────────────────


def test_free_agents_are_judged_where_the_competition_can() -> None:
    ai = FakeAI(report=WireAnswer(calls=[CallAnswer(player_id="p1", decision="ADD", drop="B", reason="Lead back.")]))

    body = (
        _client(_Wire(), ai=ai)
        .post("/api/nfl-sleeper/leagues/900/free-agents/judge", json={"player_ids": ["p1", "p2"]})
        .json()
    )

    assert ai.prompts == ["p1\np2"]
    assert [(c["player_id"], c["decision"]) for c in body] == [("p1", "ADD")]


def test_the_kept_calls_on_free_agents_are_shown_without_judging() -> None:
    answers = FakeAnswers()
    call = PlayerCall(player_id="p1", decision="WATCH", reason="Role growing.")
    answers.save(
        "wire:nfl-sleeper:900:p1", Remembered(answer=call, answered_at=datetime.now(UTC), inputs="a different line")
    )
    ai = FakeAI()

    body = (
        _client(_Wire(), ai=ai, answers=answers)
        .post("/api/nfl-sleeper/leagues/900/free-agents/calls", json={"player_ids": ["p1"]})
        .json()
    )

    assert body[0]["decision"] == "WATCH" and body[0]["stale"] is True
    assert ai.prompts == []


def test_judging_free_agents_is_refused_where_it_is_not_offered(client: TestClient) -> None:
    response = client.post("/api/premier-league-fpl/leagues/900/free-agents/judge", json={"player_ids": ["p1"]})

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported"


def test_judging_is_bounded_to_a_screen_of_players(client: TestClient) -> None:
    from thefrontoffice.application.wire import MAX_JUDGED

    ids = [f"p{i}" for i in range(MAX_JUDGED + 1)]

    assert client.post("/api/nfl-sleeper/leagues/900/free-agents/judge", json={"player_ids": ids}).status_code == 422


def test_judging_for_an_unknown_competition_is_a_404(client: TestClient) -> None:
    response = client.post("/api/cricket/leagues/900/free-agents/judge", json={"player_ids": ["p1"]})
    assert response.status_code == 404


# ── conversations ───────────────────────────────────────────────────────


def _opened(client: TestClient, key: str = ITEM.key) -> Any:
    """A conversation opened about one to-do item, as the week's row opens it."""
    return client.post("/api/premier-league/leagues/900/threads", json={"kind": "task", "key": key})


def test_a_thread_about_one_thing_opens_and_is_asked_through_the_chat() -> None:
    chat = FakeChat(reply="Because he has no fixture.")
    client = _client(ai=FakeAI(chat=chat))

    chat_id = _opened(client).json()["chat_id"]
    body = client.post(f"/api/chat/{chat_id}", json={"message": "Why bench him?"}).json()

    assert body["answer"] == "Because he has no fixture."
    assert ITEM.title in chat.sent[0]  # the first question carries the item it is about


def test_a_thread_about_an_item_since_settled_says_so(client: TestClient) -> None:
    from thefrontoffice.domain.errors import SubjectGoneError

    assert _opened(client, key="gone").json()["code"] == SubjectGoneError.code


def test_a_thread_must_name_what_it_is_about(client: TestClient) -> None:
    response = client.post("/api/premier-league/leagues/900/threads", json={"kind": "league", "key": "x"})

    assert response.status_code == 422


def test_an_expired_conversation_says_so(client: TestClient) -> None:
    """Chats live in memory, so a restart loses them. Better said than answered blankly."""
    response = client.post("/api/chat/does-not-exist", json={"message": "Hi"})

    assert response.status_code == 404


def test_a_model_failure_is_a_bad_gateway_not_a_crash() -> None:
    client = _client(ai=FakeAI(chat=FakeChat(error=RuntimeError("quota exhausted"))))

    response = client.post(f"/api/chat/{_opened(client).json()['chat_id']}", json={"message": "Why?"})

    assert response.status_code == 502


def test_a_follow_up_every_model_refused_says_why() -> None:
    """A domain error is already a sentence; flattening it to "did not answer"
    would hide that the quota, not the question, is the problem."""
    from thefrontoffice.domain.errors import AIQuotaError

    error = AIQuotaError("Gemini, Groq")
    client = _client(ai=FakeAI(chat=FakeChat(error=error)))

    response = client.post(f"/api/chat/{_opened(client).json()['chat_id']}", json={"message": "Why?"})

    assert response.json()["code"] == error.code


def test_an_empty_follow_up_is_rejected(client: TestClient) -> None:
    chat_id = _opened(client).json()["chat_id"]

    assert client.post(f"/api/chat/{chat_id}", json={"message": ""}).status_code == 422


# ── serving the built UI ────────────────────────────────────────────────


@pytest.fixture
def built_client(tmp_path: Path) -> TestClient:
    """A client with a front end built, so the catch-all route is mounted."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    return TestClient(web.create_app(fake_wiring(), dist=dist))


def test_a_view_url_returns_the_page_so_a_deep_link_loads(built_client: TestClient) -> None:
    response = built_client.get("/nfl-sleeper/900/team")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_a_built_file_is_served_as_itself(built_client: TestClient, tmp_path: Any) -> None:
    (tmp_path / "dist" / "favicon.svg").write_text("<svg/>")
    assert built_client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.parametrize("escape", ["..%2Fsecret.txt", "%2E%2E/secret.txt"])
def test_a_path_climbing_out_of_the_build_never_reads_the_file_there(
    built_client: TestClient, tmp_path: Any, escape: str
) -> None:
    """dist/ sits inside the repo, beside .env; an encoded `..` must not reach it."""
    (tmp_path / "secret.txt").write_text("API_KEY=leaked")
    response = built_client.get(f"/{escape}")
    assert "leaked" not in response.text
    assert "<title>app</title>" in response.text


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
    return TestClient(web.create_app(fake_wiring()))


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


def _model_key_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Any, dict[str, str]]:
    """A client over a throwaway .env whose reload reads that file back, and a value for every model key.

    The loop the Settings page exists for: typed in, written to .env, never read
    back, and in effect on the next request with no restart.
    """
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
    keys = {key: f"{key.lower()}-value" for key in env_file.MODEL_KEYS}
    return TestClient(web.create_app(bootstrap.wiring())), path, keys


def test_every_model_key_saved_in_settings_reaches_the_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, path, keys = _model_key_client(tmp_path, monkeypatch)

    assert client.put("/api/settings", json={"values": keys}).status_code == 200

    written = path.read_text(encoding="utf-8")
    assert all(f"{key}={value}" in written for key, value in keys.items())


def test_saving_model_keys_keeps_the_rest_of_the_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, path, keys = _model_key_client(tmp_path, monkeypatch)

    client.put("/api/settings", json={"values": keys})

    assert "SLEEPER_USERNAME=abhibeast" in path.read_text(encoding="utf-8")


def test_saved_model_keys_are_reported_present_but_never_sent_back(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, keys = _model_key_client(tmp_path, monkeypatch)

    response = client.put("/api/settings", json={"values": keys})

    listed = [s for s in response.json() if s["key"] in keys]
    assert len(listed) == len(keys) and all(s["present"] and s["secret"] for s in listed)
    assert not any(value in response.text for value in keys.values())


def test_saving_a_model_key_turns_analysis_on_without_a_restart(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, keys = _model_key_client(tmp_path, monkeypatch)
    assert client.get("/api/capabilities").json()["ai"] is False

    client.put("/api/settings", json={"values": keys})

    assert client.get("/api/capabilities").json()["ai"] is True


# ── the Yahoo handshake, driven from the UI ─────────────────────────────


def _settled(client: TestClient) -> dict[str, str]:
    """The handshake's state once it has stopped running."""
    deadline = time.monotonic() + 5
    while (state := client.get("/api/yahoo/login").json())["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    return state


def test_starting_the_handshake_returns_at_once() -> None:
    """It waits on a person and a browser tab; no request can hold that open."""
    clicked = threading.Event()
    client = TestClient(web.create_app(fake_wiring(login=FakeLogin(hold=clicked))))
    try:
        assert client.post("/api/yahoo/login").json()["status"] == "running"
    finally:
        clicked.set()


def test_a_second_start_does_not_open_a_second_browser_tab() -> None:
    clicked = threading.Event()
    login = FakeLogin(hold=clicked)
    client = TestClient(web.create_app(fake_wiring(login=login)))
    try:
        client.post("/api/yahoo/login")
        client.post("/api/yahoo/login")
    finally:
        clicked.set()
    _settled(client)

    assert login.logins == [True]


def test_a_previous_outcome_does_not_leak_into_a_new_attempt() -> None:
    """A stale "ok" would report success before anyone had clicked anything."""
    clicked = threading.Event()
    clicked.set()
    client = TestClient(web.create_app(fake_wiring(login=FakeLogin(hold=clicked))))
    client.post("/api/yahoo/login")
    assert _settled(client)["status"] == "ok"

    clicked.clear()
    try:
        assert client.post("/api/yahoo/login").json()["status"] == "running"
    finally:
        clicked.set()


def test_a_failed_handshake_is_reported_in_the_domains_words() -> None:
    from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAuthError

    client = TestClient(web.create_app(fake_wiring(login=FakeLogin(error=YahooAuthError()))))
    client.post("/api/yahoo/login")

    state = _settled(client)

    assert (state["status"], state["detail"]) == ("failed", str(YahooAuthError()))


def test_success_is_only_reported_once_the_grant_is_verified() -> None:
    """A login that completes and hands back an inert token is not a success."""
    login = FakeLogin()
    client = TestClient(web.create_app(fake_wiring(login=login)))
    client.post("/api/yahoo/login")

    assert _settled(client)["status"] == "ok"
    assert login.verified.is_set()


# ── deciding about to-do items ──────────────────────────────────────────


class _SummaryProvider(FakeProvider):
    def __init__(self, summary: Any) -> None:
        super().__init__()
        self._summary = summary

    def summary(self, league_id: str) -> Any:
        return self._summary


def _week_with_one_item() -> TestClient:
    from thefrontoffice.domain.models import Summary

    return _client(_SummaryProvider(Summary(actions=[ITEM])))


def test_a_dismissed_item_comes_back_marked_rather_than_gone() -> None:
    """Marked, so the page can hide it and still offer it back."""
    client = _week_with_one_item()

    kept = client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    ).json()
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert kept["dismissed_as"] == ITEM.fingerprint
    assert shown["hidden"] == "dismissed"


def test_a_decision_made_under_a_bare_competition_holds_under_its_key() -> None:
    """Kept by the entry it names, however the route spelled it."""
    client = _week_with_one_item()

    client.post(
        "/api/nfl/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    )
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert shown["hidden"] == "dismissed"


def test_a_restored_item_is_shown_again() -> None:
    client = _week_with_one_item()
    client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    )

    restored = client.post("/api/nfl-sleeper/leagues/L1/items", json={"key": ITEM.key, "decision": "restore"})
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

    def played_weeks(self, league_id: str) -> list[int]:
        return []

    def played_matchups(self, league_id: str, week: int) -> Any:
        return []


def test_the_week_carries_its_chance_of_winning() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_ForecastProvider(Summary()))

    body = client.get("/api/nfl-sleeper/leagues/L1/summary").json()

    assert body["forecast"]["win"] == 1.0
    assert "Win chance" in [s["label"] for s in body["headline"]]


def test_a_week_that_cannot_be_simulated_is_still_the_week() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
    from thefrontoffice.domain.models import Stat, Summary

    week = Summary(headline=[Stat(label="Week", value="7")])
    client = _client(_ForecastProvider(week, SleeperAPIError("down")))

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


def test_free_agents_carry_what_each_does_to_the_chance() -> None:
    client = _client(_WireProvider(None))

    rows = {p["player_id"]: p for p in client.get("/api/nfl-sleeper/leagues/L1/free-agents").json()["players"]}

    assert rows["starter"]["values"]["Win"] == 1.0  # a sure loss turned a sure win
    assert rows["bench"]["columns"]["Win"] == "—"


def test_sorting_by_the_chance_orders_the_page_from_the_default_ranking() -> None:
    provider = _WireProvider(None)
    client = _client(provider)

    body = client.get("/api/nfl-sleeper/leagues/L1/free-agents?sort=Win").json()

    assert provider.query.sort == ""
    assert [p["player_id"] for p in body["players"]] == ["starter", "bench"]


def test_a_free_agent_page_is_bounded_as_the_query_is() -> None:
    response = _client(_WireProvider(None)).get("/api/nfl-sleeper/leagues/L1/free-agents?limit=500")

    assert response.status_code == 422


def test_free_agents_that_cannot_be_priced_are_still_the_wire() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    client = _client(_WireProvider(None, SleeperAPIError("down")))

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


def test_the_week_carries_the_playoff_chance() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary()))

    headline = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["headline"]

    assert {s["label"]: s["value"] for s in headline}["Playoffs"] == "100%"


def test_trades_are_priced_in_playoff_chance() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary()))

    [idea] = client.get("/api/nfl-sleeper/leagues/L1/trades").json()

    assert (idea["team"], idea["giving"], idea["receiving"]) == ("Them", ["A (QB)"], ["B (WR)"])
    assert idea["playoffs_change"] > 0


class _OutlookProvider(_SummaryProvider):
    def weeks_ahead(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import WeekAhead

        return [
            WeekAhead(week=8, points=98.0, usual=121.0, missing=["A (bye)"], short=True, fix="Pick up B", gain=12.0)
        ]


def test_the_weeks_ahead_come_back_with_their_fixes() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_OutlookProvider(Summary()))

    [week] = client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead").json()

    assert (week["week"], week["short"], week["gain"]) == (8, True, 12.0)


def test_a_competition_that_cannot_look_ahead_has_no_weeks_to_plan(client: TestClient) -> None:
    """No outlook to give is an answer, not a failure."""
    assert client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead").json() == []


def test_a_competition_with_no_season_to_play_finds_no_trades(client: TestClient) -> None:
    assert client.get("/api/nfl-sleeper/leagues/L1/trades").status_code == 400


def test_the_table_carries_each_teams_playoff_chance() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary()))

    [row] = client.get("/api/nfl-sleeper/leagues/L1/schedule").json()["standings"]

    assert row["playoffs"] == "100%"


def test_a_season_that_cannot_be_simulated_is_still_the_league() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary(), SleeperAPIError("down")))

    [row] = client.get("/api/nfl-sleeper/leagues/L1/schedule").json()["standings"]
    headline = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["headline"]

    assert row["playoffs"] == "" and headline == []


def test_a_platform_that_is_down_is_a_503_that_says_so() -> None:
    """Nothing in the request was wrong, so it is not a 400."""
    from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLUnavailableError
    from thefrontoffice.domain.errors import PlatformUnavailableError

    client = _client(FakeProvider(FPLUnavailableError("FPL", "it answered 503")))

    response = client.get("/api/premier-league-fpl/leagues")

    assert response.status_code == 503
    assert response.json()["code"] == PlatformUnavailableError.code
