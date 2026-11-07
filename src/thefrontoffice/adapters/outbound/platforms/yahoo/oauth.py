"""The Yahoo OAuth2 authorization-code flow.

Written here rather than delegated because the vendor CLI's flow is subtly
wrong in a way Yahoo no longer tolerates. It authorizes against the real
redirect URI and then exchanges the code with `redirect_uri="oob"`, a value it
never authorized against. RFC 6749 §4.1.3 requires the two to be identical.
Yahoo answers that mismatch with a token rather than an error — one that
authenticates and carries no grant, so every endpoint returns 403 instead of
401, including endpoints that need no permission at all. Nothing downstream can
tell that apart from a permissions problem.

It also requests no `scope`, leaving the grant to be inferred. This asks for
`fspt-r` explicitly, which is what the app is actually going to use.

The token is written in the vendor's own persistence format, so its `Context`
keeps working and only the handshake changes.
"""

import logging
import ssl
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol

import requests
import yahoofantasy
from yahoofantasy.util import persistence

from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

FANTASY_READ_SCOPE = "fspt-r"
"""Yahoo's identifier for reading Fantasy Sports teams and leagues."""

CALLBACK_TIMEOUT_SECONDS = 300


class CallbackServer(Protocol):
    """What waiting for the redirect needs of a server: `HTTPServer`, or a test's stand-in."""

    socket: Any
    timeout: float | None

    def handle_request(self) -> None: ...

    def server_close(self) -> None: ...


ServerFactory = Callable[[tuple[str, int], type[BaseHTTPRequestHandler]], CallbackServer]


class TokenResponse(Protocol):
    """What the token exchange reads of a response."""

    status_code: int

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class Post(Protocol):
    """`requests.post`, as far as the token exchange calls it."""

    def __call__(self, url: str, *, data: dict[str, str], timeout: int) -> TokenResponse: ...


Save = Callable[[str, dict[str, Any]], None]
"""Persists the token under a key, in the vendor's own format."""

Capture = Callable[[str, str, str], str]
"""Opens the browser and waits for the code: redirect URI, client id and scope in."""

_DONE = "<html><body style='font:16px system-ui;padding:3rem'>Authorized. Close this tab.</body></html>"


def _certificate() -> tuple[Path, Path] | None:
    """A certificate for the local callback, if one is available.

    Yahoo only accepts an `https` redirect, so the callback has to be served
    over TLS even though it is localhost. The vendor package ships a
    self-signed pair for exactly this; reusing it avoids asking anyone to
    generate one, at the cost of a browser warning to click through.
    """
    directory = Path(yahoofantasy.__file__).parent / "cli"
    certificate, key = directory / "localhost.pem", directory / "localhost-key.pem"
    return (certificate, key) if certificate.exists() and key.exists() else None


class _Callback(BaseHTTPRequestHandler):
    """Catches the single redirect Yahoo makes back to this machine."""

    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Callback.code = (query.get("code") or [None])[0]
        _Callback.error = (query.get("error_description") or query.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_DONE.encode())

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default access log; this server exists for one redirect."""

    def handle_one_request(self) -> None:
        """Tolerate a connection that never becomes a request.

        A browser opens speculative connections to a host it is about to visit,
        and the certificate interstitial opens its own. Those arrive here as
        TLS or parse errors; letting one kill the server would abandon the
        handshake before the real redirect had a chance to arrive.
        """
        try:
            super().handle_one_request()
        except (ssl.SSLError, OSError) as e:
            logger.debug(f"Ignoring a connection that carried no request: {e}")
            self.close_connection = True


def capture_code(
    redirect_uri: str,
    client_id: str,
    scope: str,
    *,
    serve: ServerFactory = HTTPServer,
    open_browser: Callable[[str], object] = webbrowser.open_new_tab,
    certificate: Callable[[], tuple[Path, Path] | None] = _certificate,
    wait_seconds: float = CALLBACK_TIMEOUT_SECONDS,
) -> str:
    """Open the browser and wait for Yahoo to redirect back with a code.

    The server, the browser and the certificate arrive as arguments so a test
    can stand in for each without binding a port or opening a window.
    """
    parsed = urllib.parse.urlparse(redirect_uri)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    _Callback.code = _Callback.error = None
    server = serve(("", port), _Callback)
    if parsed.scheme == "https":
        pair = certificate()
        if pair is None:
            raise YahooLoginRequiredError()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=pair[0], keyfile=pair[1])
        server.socket = context.wrap_socket(server.socket, server_side=True)

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            # Ask to be re-consented rather than handed a stored grant. Yahoo
            # does not appear to honour this, but requesting it is correct and
            # costs nothing: without it, an app authorized before its
            # permissions were saved would silently keep the older grant.
            "prompt": "consent",
        }
    )
    url = f"{AUTH_URL}?{query}"
    logger.info(f"Opening browser for Yahoo authorization: {url}")
    open_browser(url)

    # Serve until the redirect actually arrives rather than handling a single
    # connection: the first one through is usually a browser preconnect or the
    # certificate interstitial, and treating that as the answer ends the
    # handshake a second after it began. Bounded, so a closed tab does not hang
    # the terminal the way `serve_forever` would.
    server.timeout = 1
    deadline = time.monotonic() + wait_seconds
    while _Callback.code is None and _Callback.error is None and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()

    if _Callback.error:
        # "invalid scope" is Yahoo declining to issue the permission at all,
        # which it only does when the app is not configured for it. Worth
        # separating: every other refusal here is about the user or the request,
        # and this one is about a checkbox on the app.
        if "invalid scope" in _Callback.error.lower():
            raise YahooLoginRequiredError(
                f"Yahoo rejected the {scope!r} scope, which means this application does not have "
                "Fantasy Sports enabled. At https://developer.yahoo.com/apps/ open the app, tick "
                "API Permissions → Fantasy Sports → Read, press Update, then reload the page and "
                "confirm it is still ticked before running this again."
            )
        raise YahooLoginRequiredError(f"Yahoo refused the authorization: {_Callback.error}")
    if not _Callback.code:
        raise YahooLoginRequiredError(
            f"No redirect arrived within {wait_seconds:g}s. The browser must reach "
            f"{redirect_uri} — accept the certificate warning if one appears."
        )
    return _Callback.code


def _exchange(code: str, client_id: str, client_secret: str, redirect_uri: str, post: Post) -> dict[str, Any]:
    """Trade the code for tokens, against the same redirect URI as the request."""
    response = post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            # The whole point: identical to the authorization request. Sending
            # anything else is what produced a grantless token.
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if response.status_code != 200:
        logger.error(f"Yahoo token exchange failed ({response.status_code}): {response.text[:200]}")
        raise YahooLoginRequiredError()
    return response.json()


def authorize(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    *,
    scope: str = FANTASY_READ_SCOPE,
    capture: Capture = capture_code,
    post: Post = requests.post,
    save: Save = persistence.save,
) -> None:
    """Run the full handshake and persist the result.

    Interactive: opens a browser and blocks until the redirect arrives. The
    transport arrives as arguments, so a test runs the whole handshake against
    stand-ins.

    Raises:
        YahooLoginRequiredError: the flow did not complete.
    """
    code = capture(redirect_uri, client_id, scope)
    body = _exchange(code, client_id, client_secret, redirect_uri, post)

    granted = body.get("scope")
    logger.info(f"Yahoo granted scope: {granted or '(none reported)'}")

    save(
        "auth",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": body.get("access_token"),
            "access_token_expires": time.time() + int(body.get("expires_in") or 0),
            "refresh_token": body.get("refresh_token"),
        },
    )
