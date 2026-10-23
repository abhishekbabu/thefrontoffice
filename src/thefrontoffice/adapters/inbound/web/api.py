"""HTTP API for the web UI.

An inbound adapter like the CLI: it renders errors and owns transport, and
computes nothing. The engines already return Pydantic models, so a route's
response schema is the domain model itself — `ScoutReport` and `TradeVerdict`
cross the wire exactly as the CLI renders them, with no second representation
to keep in step.

Serves the built front end from `web/dist` when it exists, so one process on one
port covers both. In development the front end runs its own dev server and calls
back here across the proxy configured in `web/vite.config.ts`.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.application.forecasting import WIN_COLUMN, attach, attach_pickups
from thefrontoffice.application.season import attach_season, attach_table
from thefrontoffice.application.wire import MAX_JUDGED, MAX_SHOWN
from thefrontoffice.bootstrap import (
    CompetitionEntry,
    ai_available,
    all_competitions,
    ask_engine,
    find,
    forecast_engine,
    item_decisions,
    scout_engine,
    season_engine,
    wire_engine,
)
from thefrontoffice.config import env_file
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import PROJECT_ROOT, settings
from thefrontoffice.config.telemetry import setup_telemetry
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import (
    ItemDecision,
    ItemState,
    LeagueSchedule,
    PlayerCall,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    PlayoffOdds,
    Remembered,
    ScoutReport,
    Subject,
    Summary,
    TeamRef,
)
from thefrontoffice.domain.ports import ChatSession, ForecastProvider, SeasonProvider

logger = logging.getLogger(__name__)

DIST = PROJECT_ROOT / "web" / "dist"


# ── wire types ──────────────────────────────────────────────────────────
# Only for shapes the domain has no model for. Anything the domain does model
# is returned as-is rather than copied into a parallel type that can drift.


class Competition(BaseModel):
    """One competition on one platform, as the picker sees it."""

    key: str
    """Identifies this entry in every route and picker: 'nba-yahoo'."""

    sport: str
    """The game itself — basketball, football, soccer — so the client can group
    the competitions that are the same sport under one heading."""

    competition: str
    """Which competition: 'nba', 'nfl', 'premier-league'."""

    platform: str
    label: str
    judges_wire: bool
    """Whether its free agents can be judged — offered only where it is."""
    configured: bool
    """Whether the credentials this competition needs are set."""

    requires: str

    ready: bool
    """Whether it can actually be used. Configured is necessary, not sufficient."""

    blocked_reason: str = ""
    blocked_code: str = ""
    """What stands in the way, and which remedy the client should offer."""


class League(BaseModel):
    league_id: str
    name: str
    detail: str
    url: str = ""
    """This league on its own platform, so a view can offer the way across."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class Reply(BaseModel):
    answer: str


class Setting(BaseModel):
    """One configurable value, described without ever carrying a secret."""

    key: str
    field: str
    secret: bool
    present: bool
    kind: str
    """Which control to render: text, boolean, integer, number or choice."""

    choices: list[str] = []
    value: str = ""
    """Empty for a secret. Presence is all the UI needs, and all it should hold."""

    shadowed: bool = False
    """A shell variable is overriding .env, so an edit here will not take effect."""

    effective: str = ""
    """What is actually in force, including a default nothing has overridden.

    An empty field with a default behind it is not unset, and showing it as
    such invites someone to type the value it already has."""


class SettingsUpdate(BaseModel):
    values: dict[str, str]


class Capabilities(BaseModel):
    """What the app can do here, as opposed to what it knows how to do."""

    ai: bool
    """Whether a model can be called. Everything that needs one hides without it."""


class LoginState(BaseModel):
    """Where the Yahoo handshake has got to."""

    status: str
    """idle, running, ok or failed."""

    detail: str = ""


class JudgeRequest(BaseModel):
    """The free agents on screen to judge, best first."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_JUDGED)


class CallsRequest(BaseModel):
    """The free agents on screen, whose kept calls to show."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_SHOWN)


class Thread(BaseModel):
    """A conversation opened about one thing; asked through the chat endpoint."""

    chat_id: str


# ── follow-up chats ─────────────────────────────────────────────────────
# A chat is a live object holding conversation state, so it cannot cross the
# wire. It stays here and the client refers to it by id. In-process because
# this serves exactly one person on one machine; a second worker would need
# somewhere shared to put these.

_chats: dict[str, ChatSession] = {}


# The Yahoo handshake opens a browser and waits for a click, which no request
# can hold open. It runs on a thread and the client watches this instead.
_login = LoginState(status="idle")
_login_lock = threading.Lock()


def _run_yahoo_login() -> None:
    """Authorize, then confirm the grant is real before reporting success."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient

    global _login
    try:
        YahooClient.login(force=True)
        YahooClient.verify()
    except FrontOfficeError as e:
        logger.error(f"Yahoo authorization failed: {e}")
        _login = LoginState(status="failed", detail=str(e))
    except Exception as e:  # a browser or socket failure, not a domain condition
        logger.error(f"Yahoo authorization failed unexpectedly: {e}")
        _login = LoginState(status="failed", detail=f"Authorization failed: {e}")
    else:
        _login = LoginState(status="ok", detail="Yahoo accepted a Fantasy Sports read.")


def _as_text(value: object) -> str:
    """Render a value the way `.env` spells it."""
    return str(value).lower() if isinstance(value, bool) else str(value or "")


def _remember(chat: ChatSession) -> str:
    chat_id = uuid.uuid4().hex
    _chats[chat_id] = chat
    return chat_id


def create_app() -> FastAPI:
    """The application, wired and ready to serve."""
    setup_logging()
    setup_telemetry("front-office-web")

    app = FastAPI(title="The Front Office", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(FrontOfficeError)
    async def _domain_error(_: Request, exc: FrontOfficeError) -> JSONResponse:
        """Every expected failure reaches the client as a readable message.

        400 rather than 500: these are all conditions the user can act on — a
        credential that is not set, a league they do not own, a misspelled
        player — not faults in the server.
        """
        logger.info(f"Domain error: {exc}")
        return JSONResponse(status_code=400, content={"detail": str(exc), "code": exc.code})

    _register_routes(app)
    _serve_frontend(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/competitions", response_model=list[Competition])
    def list_sports() -> list[Competition]:
        """Every competition, including ones this machine has no credentials for.

        Unconfigured sports are returned rather than hidden so the UI can say
        what to set instead of silently offering less than it could.
        """
        return [_sport(entry) for entry in all_competitions()]

    @app.get("/api/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        """What this installation can actually do.

        Read before anything is offered. Without a key there is no analysis to
        give, so nothing that needs one is shown — rather than shown and then
        refused, which is a click spent learning the app cannot do it.
        """
        return Capabilities(ai=ai_available())

    @app.get("/api/settings", response_model=list[Setting])
    def read_settings() -> list[Setting]:
        """Every configurable value, with secrets reported as present or absent.

        A secret's contents never leave the process. There is nothing the UI can
        do with the characters of an API key that it cannot do with the fact
        that one is set, and a page that renders them puts them in screenshots.
        """
        stored = env_file.read_values()
        return [_describe(key, field, stored.get(key, "")) for key, field in env_file.declared().items()]

    def _describe(key: str, field: str, stored: str) -> Setting:
        kind, choices = env_file.field_kind(field)
        secret = key in env_file.SECRET_KEYS
        current = getattr(settings, field, None)
        return Setting(
            key=key,
            field=field,
            secret=secret,
            present=bool(current),
            # A boolean's stored form can be absent while its value is False, so
            # the effective value is shown rather than the raw file text.
            value="" if secret else (_as_text(current) if kind == "boolean" else str(stored)),
            effective="" if secret else _as_text(current),
            kind=kind,
            choices=choices,
            shadowed=env_file.is_shadowed(key),
        )

    @app.put("/api/settings", response_model=list[Setting])
    def save_settings(update: SettingsUpdate) -> list[Setting]:
        """Write values to .env and re-read configuration into the running app.

        Rejects any key no setting reads rather than writing it: a line nothing
        picks up looks saved and changes nothing, which is the exact failure
        this endpoint exists to prevent.
        """
        try:
            env_file.write_values(update.values)
        except env_file.UnknownSettingError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OSError as e:
            logger.error(f"Could not write .env: {e}")
            raise HTTPException(status_code=500, detail=f"Could not write .env: {e}") from e
        return read_settings()

    def _sport(entry: CompetitionEntry) -> Competition:
        """A competition as the picker sees it, including why it cannot be opened.

        Offering something that will only fail on the next click is worse than
        greying it out and saying what is missing.
        """
        configured = entry.is_configured()
        reason = code = ""
        if configured:
            try:
                entry.check_ready()
            except FrontOfficeError as e:
                reason, code = str(e), e.code
        return Competition(
            key=entry.key,
            sport=entry.sport,
            competition=entry.competition,
            platform=entry.platform,
            label=entry.label,
            judges_wire=entry.judges_wire,
            configured=configured,
            requires=entry.requires,
            ready=configured and not reason,
            blocked_reason=reason,
            blocked_code=code,
        )

    @app.get("/api/yahoo/login", response_model=LoginState)
    def yahoo_login_state() -> LoginState:
        return _login

    @app.post("/api/yahoo/login", response_model=LoginState)
    def start_yahoo_login() -> LoginState:
        """Begin the handshake and return at once.

        The browser tab it opens is on this machine — the server and the person
        are the same place — but the click cannot be waited on inside a request,
        so progress is reported through the companion GET.
        """
        global _login
        with _login_lock:
            if _login.status == "running":
                return _login
            # A stale outcome from a previous attempt would read as this one's.
            _login = LoginState(status="running", detail="Authorize in the browser tab that just opened.")
        threading.Thread(target=_run_yahoo_login, daemon=True).start()
        return _login

    @app.get("/api/{competition}/leagues", response_model=list[League])
    def list_leagues(competition: str) -> list[League]:
        provider = data.build_provider(competition)
        return [League(league_id=r.league_id, name=r.name, detail=r.detail, url=r.url) for r in provider.list_leagues()]

    @app.get("/api/{competition}/leagues/{league_id}/roster", response_model=list[PlayerCard])
    def roster(competition: str, league_id: str) -> list[PlayerCard]:
        """One card per player, with per-competition columns rendered generically.

        The columns are the competition's own vocabulary — FPL sends Price and xGI,
        football sends Depth — so the client reads whatever keys arrive rather
        than being taught each competition.
        """
        return data.build_provider(competition).roster(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/players/{player_id}", response_model=PlayerDetail)
    def player(competition: str, league_id: str, player_id: str) -> PlayerDetail:
        """Everything worth knowing about one player, when someone asks."""
        return data.build_provider(competition).player(league_id, player_id)

    @app.get("/api/{competition}/leagues/{league_id}/summary", response_model=Summary)
    def summary(competition: str, league_id: str) -> Summary:
        """Where the team stands, before any report is asked for.

        The page would otherwise be blank for as long as a model call takes,
        showing nothing the app already knows. To-do items carry what the
        manager decided about them — dismissed, snoozed, or back since.
        """
        provider = data.build_provider(competition)
        summary = provider.summary(league_id)
        if isinstance(provider, ForecastProvider):
            summary = _forecast(provider, league_id, summary)
        # After the forecast, which decides how likely this week's win is.
        odds = _season(provider, league_id) if isinstance(provider, SeasonProvider) else None
        if odds is not None:
            summary = attach_season(summary, odds)
        if summary.actions is None:
            return summary
        actions = item_decisions().apply(provider.label, league_id, summary.actions)
        return summary.model_copy(update={"actions": actions})

    @app.post("/api/{competition}/leagues/{league_id}/items", response_model=ItemState | None)
    def decide(competition: str, league_id: str, decision: ItemDecision) -> ItemState | None:
        """Dismiss, snooze or restore one to-do item; the decision kept, or null once restored."""
        provider = data.build_provider(competition)
        return item_decisions().decide(provider.label, league_id, decision)

    @app.get("/api/{competition}/leagues/{league_id}/free-agents", response_model=PlayerPage)
    def free_agents(
        competition: str,
        league_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        sort: str = "",
        descending: bool = True,
        position: str = "",
        search: str = "",
    ) -> PlayerPage:
        """One page of who is still out there, best first.

        Ordering happens here rather than in the client because a football pool
        is four thousand players: a client holding fifty of them can only
        reorder those fifty, which is a worse answer than none.
        """
        # The chance of winning is priced for the page alone, so it cannot
        # rank the pool: sorting by it takes the competition's own ranking,
        # which puts the likeliest to help first, and orders that page.
        by_chance = sort == WIN_COLUMN
        query = PlayerQuery(
            offset=offset,
            limit=limit,
            sort="" if by_chance else sort,
            descending=descending,
            position=position,
            search=search,
        )
        provider = data.build_provider(competition)
        page = provider.free_agents(league_id, query)
        if not isinstance(provider, ForecastProvider):
            return page
        return _priced(provider, league_id, page, order=descending if by_chance else None)

    @app.get("/api/{competition}/leagues/{league_id}/teams", response_model=list[TeamRef])
    def teams(competition: str, league_id: str) -> list[TeamRef]:
        """Everyone in the league, so their rosters can be opened."""
        return data.build_provider(competition).teams(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/teams/{team_id}/roster", response_model=list[PlayerCard])
    def team_roster(competition: str, league_id: str, team_id: str) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own."""
        return data.build_provider(competition).roster_of(league_id, team_id)

    @app.get("/api/{competition}/leagues/{league_id}/schedule", response_model=LeagueSchedule)
    def schedule(competition: str, league_id: str) -> LeagueSchedule:
        """The league beyond this week: the season, the table, the real games.

        Separate from `summary` because it answers a different question and
        costs requests the week does not need — nobody checking their lineup
        should wait on the whole season's fixtures.
        """
        provider = data.build_provider(competition)
        schedule = provider.schedule(league_id)
        odds = _season(provider, league_id) if isinstance(provider, SeasonProvider) else None
        return attach_table(schedule, odds) if odds is not None else schedule

    @app.post("/api/{competition}/leagues/{league_id}/scout", response_model=ScoutReport)
    def scout(competition: str, league_id: str) -> ScoutReport:
        """Judge the week's to-do list — or return the kept judgment where nothing has changed."""
        return scout_engine(data.build_provider(competition)).report(league_id)

    @app.get("/api/{competition}/leagues/{league_id}/judgment", response_model=Remembered[ScoutReport] | None)
    def judgment(competition: str, league_id: str) -> Remembered[ScoutReport] | None:
        """The league's last judgment, or null — read without asking the model anything.

        What lets the week show its verdicts on load: judging is a click,
        and a reload should not throw the answer away.
        """
        provider = data.build_provider(competition)
        return scout_engine(provider).latest(league_id)

    @app.post("/api/{competition}/leagues/{league_id}/threads", response_model=Thread)
    def thread(competition: str, league_id: str, subject: Subject) -> Thread:
        """Open a conversation about one to-do item or one player.

        Seeded with that subject alone, so a question about Hall's row is
        answered about Hall's row; the turns then go through the chat endpoint
        like any other conversation.
        """
        provider = data.build_provider(competition)
        return Thread(chat_id=_remember(ask_engine(provider).open(league_id, subject)))

    @app.post("/api/{competition}/leagues/{league_id}/free-agents/judge", response_model=list[PlayerCall])
    def judge_free_agents(competition: str, league_id: str, request: JudgeRequest) -> list[PlayerCall]:
        """A call on each of the free agents on screen, to show on their rows."""
        entry = _capable(competition, "judging free agents", lambda e: e.judges_wire)
        provider = data.build_provider(entry.key)
        return wire_engine(provider).judge(league_id, request.player_ids)

    @app.post("/api/{competition}/leagues/{league_id}/free-agents/calls", response_model=list[PlayerCall])
    def free_agent_calls(competition: str, league_id: str, request: CallsRequest) -> list[PlayerCall]:
        """The kept call on each free agent on screen, without asking the model anything.

        What lets the wire show its calls on load. A player whose situation
        has moved since his call comes back marked stale.
        """
        entry = _capable(competition, "judging free agents", lambda e: e.judges_wire)
        provider = data.build_provider(entry.key)
        return wire_engine(provider).kept(league_id, request.player_ids)

    @app.post("/api/chat/{chat_id}", response_model=Reply)
    def ask(chat_id: str, request: ChatRequest) -> Reply:
        """Ask the next question in a conversation a thread opened."""
        chat = _chats.get(chat_id)
        if chat is None:
            # The server restarted, or the report predates it. Saying so is
            # better than an empty answer the user cannot explain.
            raise HTTPException(status_code=404, detail="That conversation has expired. Re-run the report.")
        try:
            answer = getattr(chat.send_message(request.message), "text", "") or ""
        except FrontOfficeError:
            # Already a sentence — "every model is out of quota" says more
            # than "did not answer", and the handler renders it with its code.
            raise
        except Exception as e:  # anything the adapters did not translate
            # Its message is a repr of a Google RPC payload; the log is where
            # that belongs, not a panel someone is reading.
            logger.error(f"Follow-up failed: {e}")
            raise HTTPException(status_code=502, detail="The model did not answer. Try asking again.") from e
        return Reply(answer=answer or "(no answer)")


def _forecast(provider: ForecastProvider, league_id: str, summary: Summary) -> Summary:
    """The week with its matchup simulated, or as it was where that cannot be done.

    Enrichment, like news and evidence: a week that cannot be simulated is
    still the week, and a page that failed over a forecast would show nothing.
    """
    try:
        result = forecast_engine(provider).forecast(league_id)
    except FrontOfficeError as e:
        logger.warning(f"Showing the week without a forecast: {e}")
        return summary
    return attach(summary, *result) if result else summary


def _season(provider: SeasonProvider, league_id: str) -> PlayoffOdds | None:
    """Every team's playoff chance, or none where the season cannot be simulated — enrichment like the forecast."""
    try:
        return season_engine(provider).odds(league_id)
    except FrontOfficeError as e:
        logger.warning(f"Showing the league without playoff odds: {e}")
        return None


def _priced(provider: ForecastProvider, league_id: str, page: PlayerPage, order: bool | None) -> PlayerPage:
    """The page with what each player would do to this week's chance; as it was where that cannot be priced."""
    try:
        chances = forecast_engine(provider).pickups(league_id, [p.player_id for p in page.players])
    except FrontOfficeError as e:
        logger.warning(f"Showing free agents without their chance of winning: {e}")
        return page
    return attach_pickups(page, chances, order=order)


def _capable(competition: str, what: str, has: Callable[[CompetitionEntry], bool]) -> CompetitionEntry:
    """The entry a route names, refusing one without the capability asked for.

    Checked here rather than left to the provider: one without the capability
    lacks the method entirely, so the failure would otherwise be an
    AttributeError rather than something the user can read. Resolved through
    `find`, which takes the registry key every route uses ("nfl-sleeper") as
    well as a bare competition — matching the bare name alone refused every
    request the UI made.
    """
    entry = find(competition)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown competition {competition!r}.")
    if not has(entry):
        raise HTTPException(status_code=400, detail=f"{entry.label} does not support {what}.")
    return entry


def _serve_frontend(app: FastAPI) -> None:
    """Serve the built UI, if it has been built.

    Mounted last so it never shadows `/api`. Missing `dist/` is the normal
    state during front-end development and while the API is under test, so it
    is not an error — the routes above work either way.
    """
    if not DIST.is_dir():
        logger.info("web/dist not built; serving the API only. Run `just ui` for the dev server.")
        return

    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Any:
        """Any non-API path returns index.html; the client owns routing.

        An unmatched API path is a 404 rather than the page, because this
        handler is the last one tried: without the check, a client asking for a
        route that has been renamed or misspelled gets index.html with a 200,
        and the failure surfaces as JSON that will not parse rather than as the
        missing route it is.
        """
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"Unknown endpoint {'/' + path!r}.")
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")


app = create_app()


def main() -> None:
    """Run the server. `just serve`."""
    import uvicorn

    uvicorn.run("thefrontoffice.adapters.inbound.web.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
