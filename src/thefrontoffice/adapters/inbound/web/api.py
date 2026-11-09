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

import argparse
import logging
import socket
import sys
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.conversation import Conversation, Turn
from thefrontoffice.adapters.inbound.remedies import ErrorBody
from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.application.wire import MAX_JUDGED, MAX_SHOWN
from thefrontoffice.bootstrap import CompetitionEntry, Wiring
from thefrontoffice.config.env_file import SettingsGroup
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import PROJECT_ROOT, settings
from thefrontoffice.config.telemetry import setup_telemetry
from thefrontoffice.domain.errors import (
    ChatExpiredError,
    ErrorCode,
    FrontOfficeError,
    InvalidRequestError,
    NotFoundError,
    PortInUseError,
)
from thefrontoffice.domain.models import (
    ItemDecision,
    ItemMark,
    Judgment,
    LeagueSchedule,
    Outlook,
    PlayerCall,
    PlayerCard,
    PlayerDetail,
    PlayerOrder,
    PlayerPage,
    PlayerQuery,
    ScoutReport,
    Subject,
    Summary,
    TeamRef,
    TradeIdea,
)
from thefrontoffice.domain.ports import (
    AccountLogin,
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
    """A question, and what was on screen when it was asked."""

    message: str = Field(min_length=1)
    on_screen: list[Subject] = Field(default_factory=list, max_length=8)


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


class JudgeRequest(BaseModel):
    """The free agents on screen to judge, best first."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_JUDGED)


class CallsRequest(BaseModel):
    """The free agents on screen, whose kept calls to show."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_SHOWN)


class Thread(BaseModel):
    """A conversation opened on the server; asked through the chat endpoint."""

    chat_id: str


MAX_CHATS = 64
"""Conversations held at once. Each carries its whole history, resent to the
model every turn, so one person's week of conversations is bounded here
rather than by how long the process happens to run."""


class _Chats:
    """Open conversations, by id, the least recently used dropped past `MAX_CHATS`.

    A chat is a live object holding conversation state, so it cannot cross the
    wire. It stays here, with what has been said in it, and the client refers
    to it by id — and reads its turns back from here, so a page reopened shows
    the conversation the server is still carrying on. One dropped answers as
    one never opened: `chat_expired`, the client's cue to open another.
    In-process because this serves exactly one person on one machine; a second
    worker would need somewhere shared to put these.
    """

    def __init__(self, limit: int = MAX_CHATS) -> None:
        self._limit = limit
        self._open: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, conversation: Conversation) -> str:
        chat_id = uuid.uuid4().hex
        with self._lock:
            self._open[chat_id] = conversation
            while len(self._open) > self._limit:
                self._open.popitem(last=False)
        return chat_id

    def get(self, chat_id: str) -> Conversation:
        """Raises:
        ChatExpiredError: this process does not hold it — it restarted since, or dropped it as the oldest.
        """
        with self._lock:
            if chat_id not in self._open:
                raise ChatExpiredError()
            self._open.move_to_end(chat_id)
            return self._open[chat_id]


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


STATUS: dict[ErrorCode, int] = {
    "unknown_competition": 404,
    "not_found": 404,
    "chat_expired": 404,
    "invalid_request": 422,
    "settings_unwritable": 500,
    "ai_failed": 502,
    "platform_unavailable": 503,
}
"""Each condition's status where it is not 400: a name nothing answers to, a request
refused unread, a fault of this server's, the model's, or a platform that is down."""


def _error_response(error: FrontOfficeError) -> JSONResponse:
    return JSONResponse(status_code=STATUS.get(error.code, 400), content=ErrorBody.of(error).model_dump())


def create_app(wiring: Wiring, *, dist: Path = DIST, max_chats: int = MAX_CHATS) -> FastAPI:
    """The application over `wiring`, serving the front end built into `dist`, holding up to `max_chats`
    conversations, ready to serve."""
    app = FastAPI(
        title="The Front Office",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        responses={status: {"model": ErrorBody} for status in sorted({400, *STATUS.values()})},
        # Named for the route's function, so the client names a response type
        # `operations["roster"]` rather than restating its path.
        generate_unique_id_function=_operation_id,
    )

    @app.exception_handler(FrontOfficeError)
    async def _domain_error(_: Request, exc: FrontOfficeError) -> JSONResponse:
        """Every expected failure reaches the client as a readable message, with its code and remedy.

        400 rather than 500 for most: a credential that is not set, a league
        they do not own, a misspelled player — conditions the user can act
        on, not faults in the server. `STATUS` names the exceptions.
        """
        logger.info(f"Domain error: {exc}")
        return _error_response(exc)

    # FastAPI's own failures are rendered the same way, so the client reads
    # one shape for every failure and never guesses a code it was not sent.
    @app.exception_handler(RequestValidationError)
    async def _refused(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(InvalidRequestError([str(error["msg"]) for error in exc.errors()]))

    @app.exception_handler(HTTPException)
    async def _unrouted(request: Request, exc: HTTPException) -> JSONResponse:
        """A path or method no route answers: the router's own 404 and 405, whose status it keeps."""
        body = ErrorBody.of(NotFoundError(f"{request.method} {request.url.path}"))
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    _register_routes(app, wiring, _Chats(max_chats))
    _serve_frontend(app, dist)
    return app


def _operation_id(route: APIRoute) -> str:
    return route.name


def serve() -> FastAPI:
    """The application as this machine runs it, built once per process: what uvicorn starts."""
    setup_logging()
    setup_telemetry("front-office-web")
    return create_app(bootstrap.wiring())


def _register_routes(app: FastAPI, wiring: Wiring, chats: _Chats) -> None:
    logins = {platform: _Login(platform, account) for platform, account in wiring.logins.items()}

    def _login(platform: str) -> _Login:
        if platform not in logins:
            raise NotFoundError(f"a login to {platform!r}")
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
        wiring.env.write_values(update.values)
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
    def roster(competition: str, league_id: str, order: Annotated[PlayerOrder, Query()]) -> list[PlayerCard]:
        """One card per player, with per-competition columns rendered generically, in the order asked.

        The columns are the competition's own vocabulary — FPL sends Price and xGI,
        football sends Depth — so the client reads whatever keys arrive rather
        than being taught each competition. Ordered here, by the rule a page of
        the wire is, so a column sorts alike on every table.
        """
        return order.ordered(_provider(competition).roster(league_id))

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

    @app.post("/api/{competition}/leagues/{league_id}/items", response_model=ItemMark)
    def decide(competition: str, league_id: str, decision: ItemDecision) -> ItemMark:
        """Dismiss, snooze or restore one to-do item; what the decision makes of it, for its row to show."""
        return wiring.decisions.decide(wiring.registry.find(competition).key, league_id, decision)

    @app.get("/api/{competition}/leagues/{league_id}/free-agents", response_model=PlayerPage)
    def free_agents(competition: str, league_id: str, query: Annotated[PlayerQuery, Query()]) -> PlayerPage:
        """One page of who is still out there, best first.

        Ordering happens here rather than in the client because a football pool
        is four thousand players: a client holding fifty of them can only
        reorder those fifty, which is a worse answer than none.
        """
        return presenting.wire(wiring.week(*_open(competition)), league_id, query)

    @app.get("/api/{competition}/leagues/{league_id}/teams", response_model=list[TeamRef])
    def teams(competition: str, league_id: str) -> list[TeamRef]:
        """Everyone in the league, so their rosters can be opened."""
        return _provider(competition).teams(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/teams/{team_id}/roster", response_model=list[PlayerCard])
    def team_roster(
        competition: str, league_id: str, team_id: str, order: Annotated[PlayerOrder, Query()]
    ) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own, ordered as yours is."""
        return order.ordered(_provider(competition).roster_of(league_id, team_id))

    @app.get("/api/{competition}/leagues/{league_id}/schedule", response_model=LeagueSchedule)
    def schedule(competition: str, league_id: str) -> LeagueSchedule:
        """The league beyond this week: the season, the table, the real games.

        Separate from `summary` because it answers a different question and
        costs requests the week does not need — nobody checking their lineup
        should wait on the whole season's fixtures.
        """
        return presenting.season(wiring.week(*_open(competition)).season(league_id))

    @app.get("/api/{competition}/leagues/{league_id}/weeks-ahead", response_model=Outlook)
    def weeks_ahead(competition: str, league_id: str) -> Outlook:
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

    @app.get("/api/{competition}/leagues/{league_id}/judgment", response_model=Judgment | None)
    def judgment(competition: str, league_id: str) -> Judgment | None:
        """The league's last judgment, or null — read without asking the model anything.

        What lets the week show its verdicts on load: judging is a click,
        and a reload should not throw the answer away.
        """
        return wiring.scout(*_open(competition)).latest(league_id)

    @app.post("/api/{competition}/leagues/{league_id}/assistant", response_model=Thread)
    def assistant(competition: str, league_id: str) -> Thread:
        """Open the conversation that follows you around this league.

        Briefed on nothing yet: each question says what is on screen, and is
        briefed on whatever of that it has not seen. The turns then go through
        the chat endpoint like any other conversation.
        """
        assistant = wiring.ask(*_open(competition)).assistant(league_id)
        return Thread(chat_id=chats.remember(Conversation(assistant)))

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

    @app.get("/api/chat/{chat_id}", response_model=list[Turn])
    def turns(chat_id: str) -> list[Turn]:
        """What has been said in a conversation so far — what a page reopened on it shows.

        An id this process does not hold is `chat_expired`, the client's cue to open another.
        """
        return chats.get(chat_id).turns

    @app.post("/api/chat/{chat_id}", response_model=list[Turn])
    def ask(chat_id: str, request: ChatRequest) -> list[Turn]:
        """Ask the next question in an open conversation; every turn so far, the answer last.

        The whole conversation rather than the answer alone, so the client shows
        what the server holds instead of keeping a copy of its own in step.
        """
        conversation = chats.get(chat_id)
        conversation.ask(request.message, request.on_screen)
        return conversation.turns


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
            raise NotFoundError(f"/{path}")
        root = dist.resolve()
        candidate = (root / path).resolve()
        # `path` arrives URL-decoded, so `..%2F` climbs out of dist/ — as far as
        # the repo's .env — unless the resolved file is held inside it.
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


HOST = "127.0.0.1"
PORTS_TRIED = 20
"""How far past the configured port `just ui` looks for a free one."""


def is_free(host: str, port: int) -> bool:
    """Whether nothing on this machine is listening on `port` yet."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
        return True


def free_port(host: str, preferred: int, tries: int = PORTS_TRIED) -> int:
    """The preferred port, or the next one up that is free.

    Raises:
        PortInUseError: none of the `tries` ports from `preferred` is free.
    """
    last = min(preferred + tries - 1, 65535)
    for port in range(preferred, last + 1):
        if is_free(host, port):
            return port
    raise PortInUseError(preferred, last)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the server: `just ui`, or `just api` with `--reload`.

    `just ui` moves up to the next free port when the configured one is taken,
    so another app on 8000 does not stop it. `--reload` keeps the configured
    port, because the Vite dev server proxies `/api` to exactly that one.
    """
    import uvicorn

    parser = argparse.ArgumentParser(description="Serve The Front Office.")
    parser.add_argument("--reload", action="store_true", help="restart on code changes, on PORT exactly")
    args = parser.parse_args(argv)
    port = settings.port
    if not args.reload:
        try:
            port = free_port(HOST, settings.port)
        except PortInUseError as e:
            sys.exit(str(e))
        if port != settings.port:
            print(f"Port {settings.port} is in use; serving on {port} instead.", flush=True)
    uvicorn.run("thefrontoffice.adapters.inbound.web.api:serve", factory=True, host=HOST, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
