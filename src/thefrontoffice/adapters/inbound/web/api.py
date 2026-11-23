"""HTTP API for the web UI.

An inbound adapter like the CLI: it renders errors and owns transport, and
computes nothing. The engines already return Pydantic models, so a route's
response schema is the domain model itself — `ScoutReport` crosses the wire
exactly as the CLI renders it, with no second representation to keep in step.

The routes live in `routes/`, one router per resource. Every collaborator
arrives in the `Wiring` `create_app` is handed, which it keeps on `app.state`
for them: `serve` builds the real one for uvicorn, and a test builds one from fakes.

Serves the built front end from `web/dist` when it exists, so one process on one
port covers both. In development the front end runs its own dev server and calls
back here across the proxy configured in `web/vite.config.ts`.
"""

import argparse
import logging
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.remedies import ErrorBody
from thefrontoffice.adapters.inbound.web.capture import CaptureGate
from thefrontoffice.adapters.inbound.web.routes import ROUTERS
from thefrontoffice.adapters.inbound.web.routes.state import MAX_CHATS, Chats, Login
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import PROJECT_ROOT, settings
from thefrontoffice.config.telemetry import setup_telemetry
from thefrontoffice.domain.errors import (
    ErrorCode,
    FrontOfficeError,
    InvalidRequestError,
    NotFoundError,
    PortInUseError,
)
from thefrontoffice.wiring import Wiring

logger = logging.getLogger(__name__)

DIST = PROJECT_ROOT / "web" / "dist"


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

    app.add_middleware(CaptureGate)
    app.state.wiring = wiring
    app.state.chats = Chats(max_chats)
    app.state.logins = {platform: Login(platform, account) for platform, account in wiring.logins.items()}
    for router in ROUTERS:
        app.include_router(router)
    _serve_frontend(app, dist)
    return app


def _operation_id(route: APIRoute) -> str:
    return route.name


def serve() -> FastAPI:
    """The application as this machine runs it, built once per process: what uvicorn starts."""
    setup_logging()
    setup_telemetry("front-office-web")
    return create_app(bootstrap.wiring())


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
    """Whether nothing on this machine is listening on `port` yet.

    Asked the way uvicorn binds — with `SO_REUSEADDR` — so a port holding only
    the closing ends of old connections reads as free, as it is to the server:
    a browser keeps those open for a minute after the last one stopped. Then
    knocked on, since that option lets a bind share a port with a listener on
    every address. Windows is left the plain bind, where the option would let
    the probe take a port somebody holds, and where a closed port answers a
    knock slowly enough to read as taken.
    """
    shared = sys.platform != "win32"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if shared:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    if not shared:
        return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as knock:
        knock.settimeout(0.2)
        return knock.connect_ex((host, port)) != 0


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
