"""HTTP API for the web UI.

An inbound adapter like the CLI: it renders errors and owns transport, and
computes nothing. The engines already return Pydantic models, so a route's
response schema is the domain model itself — `ScoutReport` crosses the wire
exactly as the CLI renders it, with no second representation to keep in step.

Every collaborator arrives in the `Wiring` `create_app` is handed: `serve`
builds the real one for uvicorn, and a test builds one from fakes.

Serves the built front end from `web/dist` when it exists, so one process on one
port covers both. In development the front end runs its own dev server and calls
back here across the proxy configured in `web/vite.config.ts`.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.remedies import Remedy, remedy
from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.application.wire import MAX_JUDGED, MAX_SHOWN
from thefrontoffice.bootstrap import CompetitionEntry, Wiring
from thefrontoffice.config.env_file import SettingsGroup, UnknownSettingError
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import PROJECT_ROOT
from thefrontoffice.config.telemetry import setup_telemetry
from thefrontoffice.domain.errors import ErrorCode, FrontOfficeError, PlatformUnavailableError, UnknownCompetitionError
from thefrontoffice.domain.models import (
    ItemDecision,
    ItemState,
    LeagueSchedule,
    PlayerCall,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    Remembered,
    ScoutReport,
    Subject,
    Summary,
    TeamRef,
    TradeIdea,
    WeekAhead,
)
from thefrontoffice.domain.ports import (
    AccountLogin,
    ChatSession,
    CompetitionProvider,
    LeagueRef,
    OutlookProvider,
    TradeMarketProvider,
    WireProvider,
)

logger = logging.getLogger(__name__)

DIST = PROJECT_ROOT / "web" / "dist"


# ── wire types ──────────────────────────────────────────────────────────
# Only for shapes the domain has no model for. Anything the domain does model
# is returned as-is rather than copied into a parallel type that can drift.


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class Reply(BaseModel):
    answer: str


class SettingsUpdate(BaseModel):
    values: dict[str, str]


class Limits(BaseModel):
    """The engines' own bounds, sent so the page can say them rather than restate them."""

    judged: int = Field(description="How many free agents one judging asks about: a screen's worth of the best.")


class Capabilities(BaseModel):
    """What the app can do here, as opposed to what it knows how to do."""

    ai: bool
    """Whether a model can be called. Everything that needs one hides without it."""

    limits: Limits


class LoginState(BaseModel):
    """Where a platform's login handshake has got to."""

    status: Literal["idle", "running", "ok", "failed"]
    detail: str = ""


class ErrorBody(BaseModel):
    """A failure the user can read, and what can be done about it."""

    detail: str
    code: ErrorCode
    remedy: Remedy | None = None


class JudgeRequest(BaseModel):
    """The free agents on screen to judge, best first."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_JUDGED)


class CallsRequest(BaseModel):
    """The free agents on screen, whose kept calls to show."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_SHOWN)


class Thread(BaseModel):
    """A conversation opened about one thing; asked through the chat endpoint."""

    chat_id: str


class _Chats:
    """Open conversations, by id.

    A chat is a live object holding conversation state, so it cannot cross the
    wire. It stays here and the client refers to it by id. In-process because
    this serves exactly one person on one machine; a second worker would need
    somewhere shared to put these.
    """

    def __init__(self) -> None:
        self._open: dict[str, ChatSession] = {}

    def remember(self, chat: ChatSession) -> str:
        chat_id = uuid.uuid4().hex
        self._open[chat_id] = chat
        return chat_id

    def get(self, chat_id: str) -> ChatSession | None:
        return self._open.get(chat_id)


class _Login:
    """One platform's handshake, which opens a browser and waits for a click no request can hold open.

    It runs on a thread, and the client watches `state` instead.
    """

    def __init__(self, platform: str, account: Callable[[], AccountLogin]) -> None:
        self._platform = platform
        self._account = account
        self._lock = threading.Lock()
        self.state = LoginState(status="idle")

    def start(self) -> LoginState:
        with self._lock:
            if self.state.status == "running":
                return self.state
            # A stale outcome from a previous attempt would read as this one's.
            self.state = LoginState(status="running", detail="Authorize in the browser tab that just opened.")
        threading.Thread(target=self._run, daemon=True).start()
        return self.state

    def _run(self) -> None:
        """Authorize, then confirm the grant is real before reporting success."""
        try:
            account = self._account()
            account.login(force=True)
            account.verify()
        except FrontOfficeError as e:
            logger.error(f"{self._platform} authorization failed: {e}")
            self.state = LoginState(status="failed", detail=str(e))
        except Exception as e:  # a browser or socket failure, not a domain condition
            logger.error(f"{self._platform} authorization failed unexpectedly: {e}")
            self.state = LoginState(status="failed", detail=f"Authorization failed: {e}")
        else:
            self.state = LoginState(status="ok", detail="The platform accepted a read with the new grant.")


def _status(error: FrontOfficeError) -> int:
    """400 for a condition the user can act on, 503 for a platform that is down, 404 for a name nothing answers to."""
    if isinstance(error, PlatformUnavailableError):
        return 503
    if isinstance(error, UnknownCompetitionError):
        return 404
    return 400


def create_app(wiring: Wiring, *, dist: Path = DIST) -> FastAPI:
    """The application over `wiring`, serving the front end built into `dist`, ready to serve."""
    app = FastAPI(
        title="The Front Office",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        responses={status: {"model": ErrorBody} for status in (400, 404, 503)},
        # Named for the route's function, so the client names a response type
        # `operations["roster"]` rather than restating its path.
        generate_unique_id_function=_operation_id,
    )

    @app.exception_handler(FrontOfficeError)
    async def _domain_error(_: Request, exc: FrontOfficeError) -> JSONResponse:
        """Every expected failure reaches the client as a readable message.

        400 rather than 500: these are all conditions the user can act on — a
        credential that is not set, a league they do not own, a misspelled
        player — not faults in the server. A platform that is down is the
        exception, and says so with 503: nothing in the request was wrong.
        """
        logger.info(f"Domain error: {exc}")
        body = ErrorBody(detail=str(exc), code=exc.code, remedy=remedy(exc))
        return JSONResponse(status_code=_status(exc), content=body.model_dump())

    _register_routes(app, wiring)
    _serve_frontend(app, dist)
    return app


def _operation_id(route: APIRoute) -> str:
    return route.name


def serve() -> FastAPI:
    """The application as this machine runs it, built once per process: what uvicorn starts."""
    setup_logging()
    setup_telemetry("front-office-web")
    return create_app(bootstrap.wiring())


def _register_routes(app: FastAPI, wiring: Wiring) -> None:
    chats = _Chats()
    logins = {platform: _Login(platform, account) for platform, account in wiring.logins.items()}

    def _login(platform: str) -> _Login:
        if platform not in logins:
            raise HTTPException(status_code=404, detail=f"Nothing logs in to {platform!r}.")
        return logins[platform]

    def _open(key: str) -> tuple[CompetitionEntry, CompetitionProvider]:
        """The entry a route names, and its provider."""
        entry = wiring.registry.find(key)
        return entry, entry.open()

    def _provider(key: str) -> CompetitionProvider:
        return wiring.registry.find(key).open()

    @app.get("/api/competitions", response_model=list[data.Competition])
    def list_sports() -> list[data.Competition]:
        """Every competition, including ones this machine has no credentials for.

        Unconfigured ones are returned rather than hidden so the UI can say
        what to set instead of silently offering less than it could.
        """
        return [data.competition(entry) for entry in wiring.registry.entries]

    @app.get("/api/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        """What this installation can actually do.

        Read before anything is offered. Without a key there is no analysis to
        give, so nothing that needs one is shown — rather than shown and then
        refused, which is a click spent learning the app cannot do it.
        """
        return Capabilities(ai=wiring.ai_available(), limits=Limits(judged=MAX_JUDGED))

    @app.get("/api/settings", response_model=list[SettingsGroup])
    def read_settings() -> list[SettingsGroup]:
        """Every configurable value, grouped by what it unlocks, with secrets reported as present or absent.

        A secret's contents never leave the process. There is nothing the UI can
        do with the characters of an API key that it cannot do with the fact
        that one is set, and a page that renders them puts them in screenshots.
        """
        return wiring.env.groups()

    @app.put("/api/settings", response_model=list[SettingsGroup])
    def save_settings(update: SettingsUpdate) -> list[SettingsGroup]:
        """Write values to .env and re-read configuration into the running app.

        Rejects any key no setting reads rather than writing it: a line nothing
        picks up looks saved and changes nothing, which is the exact failure
        this endpoint exists to prevent.
        """
        try:
            wiring.env.write_values(update.values)
        except UnknownSettingError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OSError as e:
            logger.error(f"Could not write .env: {e}")
            raise HTTPException(status_code=500, detail=f"Could not write .env: {e}") from e
        return read_settings()

    @app.get("/api/{platform}/login", response_model=LoginState)
    def login_state(platform: str) -> LoginState:
        return _login(platform).state

    @app.post("/api/{platform}/login", response_model=LoginState)
    def start_login(platform: str) -> LoginState:
        """Begin the platform's handshake and return at once.

        The browser tab it opens is on this machine — the server and the person
        are the same place — but the click cannot be waited on inside a request,
        so progress is reported through the companion GET.
        """
        return _login(platform).start()

    @app.get("/api/{competition}/leagues", response_model=list[LeagueRef])
    def list_leagues(competition: str) -> list[LeagueRef]:
        return _provider(competition).list_leagues()

    @app.get("/api/{competition}/leagues/{league_id}/roster", response_model=list[PlayerCard])
    def roster(competition: str, league_id: str) -> list[PlayerCard]:
        """One card per player, with per-competition columns rendered generically.

        The columns are the competition's own vocabulary — FPL sends Price and xGI,
        football sends Depth — so the client reads whatever keys arrive rather
        than being taught each competition.
        """
        return _provider(competition).roster(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/players/{player_id}", response_model=PlayerDetail)
    def player(competition: str, league_id: str, player_id: str) -> PlayerDetail:
        """Everything worth knowing about one player, when someone asks."""
        return _provider(competition).player(league_id, player_id)

    @app.get("/api/{competition}/leagues/{league_id}/summary", response_model=Summary)
    def summary(competition: str, league_id: str) -> Summary:
        """Where the team stands, before any report is asked for.

        The page would otherwise be blank for as long as a model call takes,
        showing nothing the app already knows. To-do items carry what the
        manager decided about them — dismissed, snoozed, or back since.
        """
        return presenting.week(wiring.week(*_open(competition)).week(league_id))

    @app.post("/api/{competition}/leagues/{league_id}/items", response_model=ItemState | None)
    def decide(competition: str, league_id: str, decision: ItemDecision) -> ItemState | None:
        """Dismiss, snooze or restore one to-do item; the decision kept, or null once restored."""
        return wiring.decisions.decide(wiring.registry.find(competition).key, league_id, decision)

    @app.get("/api/{competition}/leagues/{league_id}/free-agents", response_model=PlayerPage)
    def free_agents(competition: str, league_id: str, query: Annotated[PlayerQuery, Query()]) -> PlayerPage:
        """One page of who is still out there, best first.

        Ordering happens here rather than in the client because a football pool
        is four thousand players: a client holding fifty of them can only
        reorder those fifty, which is a worse answer than none.
        """
        view = wiring.week(*_open(competition)).wire(league_id, presenting.ranking(query))
        return presenting.wire(view, query)

    @app.get("/api/{competition}/leagues/{league_id}/teams", response_model=list[TeamRef])
    def teams(competition: str, league_id: str) -> list[TeamRef]:
        """Everyone in the league, so their rosters can be opened."""
        return _provider(competition).teams(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/teams/{team_id}/roster", response_model=list[PlayerCard])
    def team_roster(competition: str, league_id: str, team_id: str) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own."""
        return _provider(competition).roster_of(league_id, team_id)

    @app.get("/api/{competition}/leagues/{league_id}/schedule", response_model=LeagueSchedule)
    def schedule(competition: str, league_id: str) -> LeagueSchedule:
        """The league beyond this week: the season, the table, the real games.

        Separate from `summary` because it answers a different question and
        costs requests the week does not need — nobody checking their lineup
        should wait on the whole season's fixtures.
        """
        return presenting.season(wiring.week(*_open(competition)).season(league_id))

    @app.get("/api/{competition}/leagues/{league_id}/weeks-ahead", response_model=list[WeekAhead])
    def weeks_ahead(competition: str, league_id: str) -> list[WeekAhead]:
        """The next few weeks as your roster stands, and a pickup for any that comes up short.

        Offered only where a competition can project them, as trades are, so
        one that cannot refuses rather than answering with no weeks.
        """
        provider = wiring.registry.find(competition).open_as(OutlookProvider, "planning the weeks ahead")
        return provider.weeks_ahead(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/trades", response_model=list[TradeIdea])
    def trades(competition: str, league_id: str) -> list[TradeIdea]:
        """The trades that would most raise your playoff chance and that the other side gains from too.

        Its own route because it plays the season out once per trade tried —
        seconds, not the instant a table should take to appear.
        """
        provider = wiring.registry.find(competition).open_as(TradeMarketProvider, "finding trades")
        return wiring.market(provider).trades(league_id)

    @app.post("/api/{competition}/leagues/{league_id}/scout", response_model=ScoutReport)
    def scout(competition: str, league_id: str) -> ScoutReport:
        """Judge the week's to-do list — or return the kept judgment where nothing has changed."""
        return wiring.scout(*_open(competition)).report(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/judgment", response_model=Remembered[ScoutReport] | None)
    def judgment(competition: str, league_id: str) -> Remembered[ScoutReport] | None:
        """The league's last judgment, or null — read without asking the model anything.

        What lets the week show its verdicts on load: judging is a click,
        and a reload should not throw the answer away.
        """
        return wiring.scout(*_open(competition)).latest(league_id)

    @app.post("/api/{competition}/leagues/{league_id}/threads", response_model=Thread)
    def thread(competition: str, league_id: str, subject: Subject) -> Thread:
        """Open a conversation about one to-do item or one player.

        Seeded with that subject alone, so a question about Hall's row is
        answered about Hall's row; the turns then go through the chat endpoint
        like any other conversation.
        """
        return Thread(chat_id=chats.remember(wiring.ask(*_open(competition)).open(league_id, subject)))

    @app.post("/api/{competition}/leagues/{league_id}/free-agents/judge", response_model=list[PlayerCall])
    def judge_free_agents(competition: str, league_id: str, request: JudgeRequest) -> list[PlayerCall]:
        """A call on each of the free agents on screen, to show on their rows."""
        entry = wiring.registry.find(competition)
        provider = entry.open_as(WireProvider, "judging free agents")
        return wiring.wire(entry, provider).judge(league_id, request.player_ids)

    @app.post("/api/{competition}/leagues/{league_id}/free-agents/calls", response_model=list[PlayerCall])
    def free_agent_calls(competition: str, league_id: str, request: CallsRequest) -> list[PlayerCall]:
        """The kept call on each free agent on screen, without asking the model anything.

        What lets the wire show its calls on load. A player whose situation
        has moved since his call comes back marked stale.
        """
        entry = wiring.registry.find(competition)
        provider = entry.open_as(WireProvider, "judging free agents")
        return wiring.wire(entry, provider).kept(league_id, request.player_ids)

    @app.post("/api/chat/{chat_id}", response_model=Reply)
    def ask(chat_id: str, request: ChatRequest) -> Reply:
        """Ask the next question in a conversation a thread opened."""
        chat = chats.get(chat_id)
        if chat is None:
            # The server restarted, or the report predates it. Saying so is
            # better than an empty answer the user cannot explain.
            raise HTTPException(status_code=404, detail="That conversation has expired. Close it and ask again.")
        try:
            answer = chat.send_message(request.message).text
        except FrontOfficeError:
            # Already a sentence — "every model is out of quota" says more
            # than "did not answer", and the handler renders it with its code.
            raise
        except Exception as e:  # anything the adapters did not translate
            # Its message is a repr of a vendor's RPC payload; the log is where
            # that belongs, not a panel someone is reading.
            logger.error(f"Follow-up failed: {e}")
            raise HTTPException(status_code=502, detail="The model did not answer. Try asking again.") from e
        return Reply(answer=answer)


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built UI, if it has been built.

    Mounted last so it never shadows `/api`. Missing `dist/` is the normal
    state during front-end development and while the API is under test, so it
    is not an error — the routes above work either way.
    """
    if not dist.is_dir():
        logger.info("web/dist not built; serving the API only. Run `just ui` for the dev server.")
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Any non-API path returns index.html; the client owns routing.

        An unmatched API path is a 404 rather than the page, because this
        handler is the last one tried: without the check, a client asking for a
        route that has been renamed or misspelled gets index.html with a 200,
        and the failure surfaces as JSON that will not parse rather than as the
        missing route it is.
        """
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"Unknown endpoint {'/' + path!r}.")
        root = dist.resolve()
        candidate = (root / path).resolve()
        # `path` arrives URL-decoded, so `..%2F` climbs out of dist/ — as far as
        # the repo's .env — unless the resolved file is held inside it.
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


def main() -> None:
    """Run the server: `just ui`."""
    import uvicorn

    uvicorn.run("thefrontoffice.adapters.inbound.web.api:serve", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
