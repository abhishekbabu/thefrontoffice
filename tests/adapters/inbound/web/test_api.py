"""Tests for the web API.

The routes own transport and error rendering, so that is what is asserted here:
which status a failure becomes, what a client is told, and that a domain model
crosses the wire unchanged. The reports themselves are the engines' tests.

Every app is built over a wiring of fakes from `support/wiring.py`: nothing is
patched, and nothing leaves the process.
"""

import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.ai import FakeAI, FakeChat
from support.reports import MOCK_FPL_REPORT
from support.settings import NOWHERE, isolated_settings
from support.simulation import FakeForecast
from support.stores import FakeAnswers
from support.wiring import FakeCompetition, FakeLogin, entry
from support.wiring import wiring as fake_wiring

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.web import api as web
from thefrontoffice.application.formats import CallAnswer, WireAnswer
from thefrontoffice.application.scouting import scout_scope
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import AppSettings, env_var
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    LeagueSchedule,
    MatchupInput,
    Outlook,
    PlayerCall,
    PlayerCard,
    PlayerPage,
    PlayerQuery,
    Remembered,
    SeasonInput,
    Summary,
    TradeMarket,
    TradeProposal,
)
from thefrontoffice.domain.ports import LeagueRef

REGISTRY = bootstrap.registry(isolated_settings(NOWHERE))
"""The app's competitions, none of them configured: what every fake entry here borrows its identity from."""

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

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
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
            needs=e.needs,
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
    flags = {c["key"]: (c["judges_wire"], c["plans_weeks"], c["finds_trades"]) for c in body}

    assert flags["nfl-sleeper"] == (True, True, True) and flags["premier-league-fpl"] == (False, False, False)


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


class _Squad(FakeProvider):
    def roster(self, league_id: str) -> list[PlayerCard]:
        return [
            PlayerCard(player_id="1", columns={"Player": "Cheap", "Price": "£4.5m"}, values={"Price": 4.5}),
            PlayerCard(player_id="2", columns={"Player": "Dear", "Price": "£15.5m"}, values={"Price": 15.5}),
            PlayerCard(player_id="3", columns={"Player": "Mid", "Price": "£9.0m"}, values={"Price": 9.0}),
        ]


def test_a_roster_is_ordered_by_the_column_asked_for_as_a_page_of_the_wire_is() -> None:
    """By the number behind the column: '£15.5m' sorted as text sits below '£9.0m'."""
    client = _client(_Squad())

    body = client.get("/api/premier-league/leagues/900/roster", params={"sort": "Price", "descending": True}).json()

    assert [card["player_id"] for card in body] == ["2", "3", "1"]


def test_a_roster_says_which_columns_hold_the_name_status_and_slot(client: TestClient) -> None:
    """So the page renders them by role, never by matching a column's name."""
    [card] = client.get("/api/premier-league/leagues/900/roster").json()

    assert card["roles"] == {"Player": "player"}


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
    assert (body["remedy"]["action"], body["remedy"]["platform"]) == ("authorize", "yahoo")


def test_the_app_says_its_limits_rather_than_leaving_the_page_to_restate_them(client: TestClient) -> None:
    from thefrontoffice.application.wire import MAX_JUDGED

    limits = client.get("/api/capabilities").json()["limits"]

    assert limits == {"judged": MAX_JUDGED}


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

    assert body[-1] == {"role": "model", "text": "Because he has no fixture."}
    assert ITEM.title in chat.sent[0]  # the first question carries the item it is about


def test_a_thread_about_an_item_since_settled_says_so(client: TestClient) -> None:
    from thefrontoffice.domain.errors import SubjectGoneError

    assert _opened(client, key="gone").json()["code"] == SubjectGoneError.code


def test_a_thread_must_name_what_it_is_about(client: TestClient) -> None:
    response = client.post("/api/premier-league/leagues/900/threads", json={"kind": "league", "key": "x"})

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_expired_conversation_says_so_with_a_code_the_page_can_act_on(client: TestClient, method: str) -> None:
    """Chats live in memory, so a restart loses them. The page kept the old id
    and was stuck on it: the code is what tells it to open a fresh one."""
    response = client.request(method.upper(), "/api/chat/does-not-exist", json={"message": "Hi"})

    assert (response.status_code, response.json()["code"]) == (404, "chat_expired")


def test_a_reopened_conversation_reads_back_what_was_said() -> None:
    """The server carries the conversation on, so a page reopened on it shows it rather than a blank."""
    client = _client(ai=FakeAI(chat=FakeChat(reply="Because he has no fixture.")))
    chat_id = _opened(client).json()["chat_id"]
    client.post(f"/api/chat/{chat_id}", json={"message": "Why bench him?"})

    turns = client.get(f"/api/chat/{chat_id}").json()

    assert [(t["role"], t["text"]) for t in turns] == [
        ("you", "Why bench him?"),
        ("model", "Because he has no fixture."),
    ]


def test_a_follow_up_answers_with_the_whole_conversation_as_the_server_holds_it() -> None:
    """The page shows what it is sent rather than appending a copy it must keep in step."""
    client = _client(ai=FakeAI(chat=FakeChat(reply="Because.")))
    chat_id = _opened(client).json()["chat_id"]
    client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    body = client.post(f"/api/chat/{chat_id}", json={"message": "Really?"}).json()

    assert body == client.get(f"/api/chat/{chat_id}").json()
    assert [t["text"] for t in body if t["role"] == "you"] == ["Why?", "Really?"]


def test_the_server_holds_a_bounded_number_of_conversations_dropping_the_least_recently_used() -> None:
    """Each one carries its whole history; kept for as long as the process runs, they only grow."""
    fpl = entry(FakeProvider(), competition="premier-league", platform="fpl")
    client = TestClient(web.create_app(fake_wiring(fpl), max_chats=2))
    first, second = (_opened(client).json()["chat_id"] for _ in range(2))
    client.get(f"/api/chat/{first}")  # read since, so the second is now the oldest

    _opened(client)

    assert client.get(f"/api/chat/{first}").status_code == 200
    assert client.get(f"/api/chat/{second}").json()["code"] == "chat_expired"


def test_a_model_failure_is_a_bad_gateway_not_a_crash() -> None:
    client = _client(ai=FakeAI(chat=FakeChat(error=RuntimeError("quota exhausted"))))

    response = client.post(f"/api/chat/{_opened(client).json()['chat_id']}", json={"message": "Why?"})

    assert (response.status_code, response.json()["code"]) == (502, "ai_failed")
    assert "quota exhausted" not in response.json()["detail"]  # a vendor's repr belongs in the log


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

    response = client.post(f"/api/chat/{chat_id}", json={"message": ""})

    assert (response.status_code, response.json()["code"]) == (422, "invalid_request")
    assert isinstance(response.json()["detail"], str)  # one sentence, not FastAPI's field list


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


def test_a_built_file_is_served_as_itself(built_client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "dist" / "favicon.svg").write_text("<svg/>")
    assert built_client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.parametrize("escape", ["..%2Fsecret.txt", "%2E%2E/secret.txt"])
def test_a_path_climbing_out_of_the_build_never_reads_the_file_there(
    built_client: TestClient, tmp_path: Path, escape: str
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
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_a_route_that_does_not_exist_carries_a_code_like_any_failure(client: TestClient) -> None:
    """Without the page built, the router answers itself — in the same shape."""
    response = client.get("/api/does-not-exist")
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_a_platform_with_no_login_is_a_404_with_its_code(client: TestClient) -> None:
    response = client.post("/api/cricket/login")
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


# ── settings ────────────────────────────────────────────────────────────


def _settings_client(path: Path, **config: Any) -> TestClient:
    """A client editing a throwaway .env, with settings of its own, rather than the developer's."""
    return TestClient(web.create_app(fake_wiring(env=EnvFile(path, settings=AppSettings(_env_file=None, **config)))))


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=abhibeast\n", encoding="utf-8")
    return path


@pytest.fixture
def settings_client(env_path: Path) -> TestClient:
    return _settings_client(env_path, sleeper_username="abhibeast")


def _listed(body: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """One setting out of the groups the page is sent."""
    return next(s for group in body for s in group["settings"] if s["key"] == key)


def test_settings_list_every_variable_the_app_reads(settings_client: TestClient) -> None:
    body = settings_client.get("/api/settings").json()
    keys = {s["key"] for group in body for s in group["settings"]}
    assert {"GOOGLE_API_KEY", "FPL_ENTRY_ID", "SLEEPER_USERNAME"} <= keys


def test_settings_arrive_grouped_with_what_each_group_unlocks(settings_client: TestClient) -> None:
    """So the page renders the server's groups rather than keeping a list of keys of its own."""
    body = settings_client.get("/api/settings").json()

    ai = next(group for group in body if any(s["key"] == "GOOGLE_API_KEY" for s in group["settings"]))
    assert ai["note"] and {"GROQ_API_KEY", "OPENROUTER_API_KEY"} <= {s["key"] for s in ai["settings"]}


def test_a_secret_is_never_sent_to_the_client(env_path: Path) -> None:
    """There is nothing the UI can do with the characters of an API key that it
    cannot do with the fact that one is set — and a page that renders them puts
    them in screenshots."""
    response = _settings_client(env_path, groq_api_key="super-secret-value").get("/api/settings")

    entry = _listed(response.json(), "GROQ_API_KEY")
    assert (entry["secret"], entry["present"], entry["value"], entry["effective"]) == (True, True, "", "")
    assert "super-secret-value" not in response.text


def test_a_non_secret_carries_its_value_so_it_can_be_edited(settings_client: TestClient) -> None:
    assert _listed(settings_client.get("/api/settings").json(), "SLEEPER_USERNAME")["value"] == "abhibeast"


def test_saving_writes_the_value_and_returns_the_new_state(settings_client: TestClient) -> None:
    body = settings_client.put("/api/settings", json={"values": {"FPL_ENTRY_ID": "4242"}}).json()

    assert _listed(body, "FPL_ENTRY_ID")["value"] == "4242"


def test_a_key_no_setting_reads_is_refused_with_its_name(settings_client: TestClient) -> None:
    response = settings_client.put("/api/settings", json={"values": {"GOOGLE_APIKEY": "oops"}})

    assert (response.status_code, response.json()["code"]) == (400, "unknown_setting")
    assert "GOOGLE_APIKEY" in response.json()["detail"]


def test_an_env_that_cannot_be_written_is_a_server_fault_that_says_so(tmp_path: Path) -> None:
    """A directory where the file should be: nothing the request did wrong."""
    path = tmp_path / ".env"
    path.mkdir()

    response = _settings_client(path).put("/api/settings", json={"values": {"FPL_ENTRY_ID": "4242"}})

    assert (response.status_code, response.json()["code"]) == (500, "settings_unwritable")


def test_a_shell_variable_is_reported_so_a_futile_edit_is_visible(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FPL_ENTRY_ID", "999")

    assert _listed(settings_client.get("/api/settings").json(), "FPL_ENTRY_ID")["shadowed"] is True


def _model_key_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path, dict[str, str]]:
    """The app as bootstrap wires it, over a throwaway .env, and a value for every model key.

    The loop the Settings page exists for: typed in, written to .env, never read
    back, and in effect on the next request with no restart. The settings are
    the test's own; a save reloads them from the file and the environment, so
    no model key in this shell may leak in.
    """
    for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
        monkeypatch.delenv(env_var(field), raising=False)
    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=abhibeast\n", encoding="utf-8")
    wiring = bootstrap.wiring(isolated_settings(tmp_path, sleeper_username="abhibeast"), env=path)
    keys = {env_var(field): f"{field}-value" for field in ("gemini_api_key", "groq_api_key", "openrouter_api_key")}
    return TestClient(web.create_app(wiring)), path, keys


def test_every_model_key_saved_in_settings_reaches_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, path, keys = _model_key_client(tmp_path, monkeypatch)

    assert client.put("/api/settings", json={"values": keys}).status_code == 200

    written = path.read_text(encoding="utf-8")
    assert all(f"{key}={value}" in written for key, value in keys.items())


def test_saving_model_keys_keeps_the_rest_of_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, path, keys = _model_key_client(tmp_path, monkeypatch)

    client.put("/api/settings", json={"values": keys})

    assert "SLEEPER_USERNAME=abhibeast" in path.read_text(encoding="utf-8")


def test_saved_model_keys_are_reported_present_but_never_sent_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, keys = _model_key_client(tmp_path, monkeypatch)

    response = client.put("/api/settings", json={"values": keys})

    listed = [_listed(response.json(), key) for key in keys]
    assert all(s["present"] and s["secret"] for s in listed)
    assert not any(value in response.text for value in keys.values())


def test_saving_a_model_key_turns_analysis_on_without_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    def __init__(self, summary: Summary | None) -> None:
        super().__init__()
        self._summary = summary or Summary()

    def summary(self, league_id: str) -> Summary:
        return self._summary


def _week_with_one_item() -> TestClient:
    from thefrontoffice.domain.models import Summary

    return _client(_SummaryProvider(Summary(actions=[ITEM])))


def test_a_dismissed_item_comes_back_marked_rather_than_gone() -> None:
    """Marked, so the page can hide it and still offer it back — and the decision answers with that same mark."""
    client = _week_with_one_item()

    kept = client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    ).json()
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert kept == shown["mark"]
    assert shown["mark"]["hidden"] == "dismissed"


def test_the_week_carries_the_last_verdict_on_each_item() -> None:
    """Joined on the server, so the page shows what it is sent rather than matching keys itself."""
    from thefrontoffice.domain.models import Summary, TaskVerdict

    verdict = TaskVerdict(task="T1", decision="WAIT", reason="His status is due Sunday.")
    answers = FakeAnswers()
    judged = MOCK_FPL_REPORT.model_copy(update={"tasks": [ITEM.model_copy(update={"verdict": verdict})]})
    answers.save(scout_scope("nfl-sleeper", "L1"), Remembered(answer=judged, answered_at=datetime.now(UTC), inputs=""))
    changed = ITEM.model_copy(update={"reason": "+6.0"})

    [shown] = (
        _client(_SummaryProvider(Summary(actions=[changed])), answers=answers)
        .get("/api/nfl-sleeper/leagues/L1/summary")
        .json()["actions"]
    )

    assert (shown["verdict"]["decision"], shown["stale"]) == ("WAIT", True)


def test_a_decision_made_under_a_bare_competition_holds_under_its_key() -> None:
    """Kept by the entry it names, however the route spelled it."""
    client = _week_with_one_item()

    client.post(
        "/api/nfl/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    )
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert shown["mark"]["hidden"] == "dismissed"


def test_a_restored_item_is_shown_again() -> None:
    client = _week_with_one_item()
    client.post(
        "/api/nfl-sleeper/leagues/L1/items",
        json={"key": ITEM.key, "decision": "dismiss", "fingerprint": ITEM.fingerprint},
    )

    restored = client.post("/api/nfl-sleeper/leagues/L1/items", json={"key": ITEM.key, "decision": "restore"})
    [shown] = client.get("/api/nfl-sleeper/leagues/L1/summary").json()["actions"]

    assert restored.json() == shown["mark"]
    assert shown["mark"]["hidden"] is None


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


class _ForecastProvider(FakeForecast, _SummaryProvider):
    """A provider whose matchup can be simulated, or whose forecast fails."""

    def __init__(self, summary: Summary | None, error: Exception | None = None) -> None:
        _SummaryProvider.__init__(self, summary)
        FakeForecast.__init__(self, error)

    def matchup(self, candidates: Sequence[str]) -> MatchupInput:
        from thefrontoffice.domain.models import MatchupInput, Outcomes

        return MatchupInput(mine=(Outcomes("a", "A", 20.0, (20.0,)),), theirs=(Outcomes("b", "B", 10.0, (10.0,)),))


class _WireProvider(_ForecastProvider):
    """A forecastable provider with two free agents, one of whom can start."""

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        from thefrontoffice.domain.models import PlayerPage

        self.query = query
        return PlayerPage(
            players=[PlayerCard(player_id=pid, columns={"Player": pid}) for pid in ("bench", "starter")], total=2
        )

    def matchup(self, candidates: Sequence[str]) -> MatchupInput:
        from thefrontoffice.domain.models import LineupMove, MatchupInput, Outcomes

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


def test_a_free_agent_page_is_bounded_as_the_query_is() -> None:
    response = _client(_WireProvider(None)).get("/api/nfl-sleeper/leagues/L1/free-agents?limit=500")

    assert response.status_code == 422


class _SeasonProvider(_SummaryProvider):
    """A provider whose season can be simulated, or whose simulation fails."""

    def __init__(self, summary: Summary | None, error: Exception | None = None) -> None:
        super().__init__(summary)
        self.error = error

    def season_input(self, league_id: str) -> SeasonInput:
        from thefrontoffice.domain.models import SeasonInput, TeamRecord

        if self.error:
            raise self.error
        teams = (TeamRecord("1", "Me", 6, 0, 0, 900.0), TeamRecord("2", "Them", 0, 6, 0, 500.0))
        return SeasonInput(teams=teams, fixtures=(), scoring=(), spots=1, mine="1", week=7)

    def trade_market(self, league_id: str) -> TradeMarket:
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

    def schedule(self, league_id: str) -> LeagueSchedule:
        from thefrontoffice.domain.models import LeagueSchedule, StandingRow

        return LeagueSchedule(standings=[StandingRow(rank=1, name="Me", team_id="1")])


def test_trades_are_priced_in_playoff_chance() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary()))

    [idea] = client.get("/api/nfl-sleeper/leagues/L1/trades").json()

    assert (idea["team"], idea["giving"], idea["receiving"]) == ("Them", ["A (QB)"], ["B (WR)"])
    assert idea["playoffs_change"] > 0


class _OutlookProvider(_SummaryProvider):
    def weeks_ahead(self, league_id: str) -> Outlook:
        from thefrontoffice.domain.models import WeekAhead

        week = WeekAhead(
            week=8, points=98.0, short_by=23.0, missing=["A (bye)"], short=True, fix="Pick up B", gain=12.0
        )
        return Outlook(usual=121.0, weeks=[week])


def test_the_weeks_ahead_come_back_with_their_fixes() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_OutlookProvider(Summary()))

    outlook = client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead").json()
    [week] = outlook["weeks"]

    assert outlook["usual"] == 121.0
    assert (week["week"], week["short"], week["short_by"], week["gain"]) == (8, True, 23.0, 12.0)


def test_a_competition_that_cannot_look_ahead_refuses_as_it_does_trades(client: TestClient) -> None:
    """Only offered where it can be, so asking anyway is refused rather than answered with no weeks."""
    response = client.get("/api/nfl-sleeper/leagues/L1/weeks-ahead")

    assert (response.status_code, response.json()["code"]) == (400, "unsupported")


def test_a_competition_with_no_season_to_play_finds_no_trades(client: TestClient) -> None:
    assert client.get("/api/nfl-sleeper/leagues/L1/trades").status_code == 400


def test_the_table_carries_each_teams_playoff_chance() -> None:
    from thefrontoffice.domain.models import Summary

    client = _client(_SeasonProvider(Summary()))

    [row] = client.get("/api/nfl-sleeper/leagues/L1/schedule").json()["standings"]

    assert row["playoffs"] == "100%"


def test_a_platform_that_is_down_is_a_503_that_says_so() -> None:
    """Nothing in the request was wrong, so it is not a 400."""
    from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLUnavailableError
    from thefrontoffice.domain.errors import PlatformUnavailableError

    client = _client(FakeProvider(FPLUnavailableError("it answered 503")))

    response = client.get("/api/premier-league-fpl/leagues")

    assert response.status_code == 503
    assert response.json()["code"] == PlatformUnavailableError.code


def test_a_platform_nothing_logs_in_to_is_a_404() -> None:
    assert TestClient(web.create_app(fake_wiring())).post("/api/espn/login").status_code == 404
