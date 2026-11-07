"""Tests for the Yahoo OAuth2 handshake.

The browser half cannot be exercised hermetically, so what is asserted here is
the half that was wrong: which parameters go out, and that the two halves agree
about the redirect URI. The server, the browser, the token exchange and the
token file are each handed in, so nothing is bound, opened, posted or written.
"""

import time
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from support.http import FakeResponse

from thefrontoffice.adapters.outbound.platforms.yahoo import oauth
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

REDIRECT = "https://localhost:8080"

GRANTED = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "fspt-r"}


class Exchange:
    """Answers the token exchange without making one, keeping what was posted."""

    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse(GRANTED)
        self.posted: list[dict[str, str]] = []

    def __call__(self, url: str, *, data: dict[str, str], timeout: int) -> FakeResponse:
        self.posted.append(data)
        return self.response


class Saved:
    """Keeps what would be persisted, rather than writing a token file."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, key: str, value: dict[str, Any]) -> None:
        self.calls.append((key, value))


def _clicked(redirect_uri: str, client_id: str, scope: str) -> str:
    """Skips the browser, returning a code as though someone had clicked."""
    return "the-code"


def _authorize(exchange: Exchange, saved: Saved, capture: oauth.Capture = _clicked) -> None:
    oauth.authorize("id", "secret", REDIRECT, capture=capture, post=exchange, save=saved)


# ── the bug this module exists for ──────────────────────────────────────


def test_the_exchange_quotes_back_the_same_redirect_uri() -> None:
    """RFC 6749 §4.1.3 requires it, and Yahoo answers a mismatch with a token
    rather than an error — one that authenticates and grants nothing."""
    exchange = Exchange()
    _authorize(exchange, Saved())

    assert exchange.posted[0]["redirect_uri"] == REDIRECT


def test_the_exchange_sends_an_authorization_code_grant() -> None:
    exchange = Exchange()
    _authorize(exchange, Saved())

    assert exchange.posted[0]["grant_type"] == "authorization_code"
    assert exchange.posted[0]["code"] == "the-code"
    assert exchange.posted[0]["client_id"] == "id"


def test_fantasy_read_is_requested_explicitly() -> None:
    """Leaving scope to be inferred is what makes an empty grant possible."""
    seen: list[str] = []

    def _capture(redirect_uri: str, client_id: str, scope: str) -> str:
        seen.append(scope)
        return "c"

    _authorize(Exchange(), Saved(), capture=_capture)

    assert seen == ["fspt-r"]


# ── the authorization request ───────────────────────────────────────────


class OneShotServer:
    """Stands in for the callback server: serves a scripted connection per `handle_request`, binding nothing."""

    def __init__(self, arrivals: list[tuple[str | None, str | None]] | None = None) -> None:
        self.arrivals = list(arrivals or [])
        self.handled = 0
        self.closed = False
        self.socket: Any = None
        self.timeout: float | None = None

    def __call__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> OneShotServer:
        """Built the way `HTTPServer` is."""
        return self

    def handle_request(self) -> None:
        self.handled += 1
        if self.arrivals:
            code, error = self.arrivals.pop(0)
            if code:
                oauth._Callback.code = code
            if error:
                oauth._Callback.error = error

    def server_close(self) -> None:
        self.closed = True


def _no_certificate() -> None:
    return None


def _no_browser(url: str) -> None:
    return None


def _capture(server: OneShotServer, wait_seconds: float = 5) -> str:
    """The handshake's wait, against `server` and no browser."""
    return oauth.capture_code(
        "http://localhost:9999",
        "id",
        "fspt-r",
        serve=server,
        open_browser=_no_browser,
        certificate=_no_certificate,
        wait_seconds=wait_seconds,
    )


def test_without_a_certificate_the_browser_is_never_opened() -> None:
    """Yahoo redirects to https, which nothing here could answer without one."""
    opened: list[str] = []

    with pytest.raises(YahooLoginRequiredError):
        oauth.capture_code(
            REDIRECT, "the-id", "fspt-r", serve=OneShotServer(), open_browser=opened.append, certificate=_no_certificate
        )

    # No certificate means the server was never started, so nothing opened.
    assert opened == []


def test_the_url_is_built_from_the_same_redirect_uri() -> None:
    """Built here and quoted back in the exchange; they must not drift apart."""
    captured: dict[str, list[str]] = {}

    def _open(url: str) -> None:
        captured.update(parse_qs(urlparse(url).query))
        raise RuntimeError("stop before the wait")

    with pytest.raises(RuntimeError):
        oauth.capture_code("http://localhost:9999", "the-id", "fspt-r", serve=OneShotServer(), open_browser=_open)

    assert captured["redirect_uri"] == ["http://localhost:9999"]
    assert captured["client_id"] == ["the-id"]
    assert captured["scope"] == ["fspt-r"]
    assert captured["response_type"] == ["code"]


# ── failures ────────────────────────────────────────────────────────────


def test_a_refused_exchange_raises_rather_than_saving_nothing() -> None:
    """Persisting a half-token would look authorized and fail on first use."""
    saved = Saved()

    with pytest.raises(YahooLoginRequiredError):
        _authorize(Exchange(FakeResponse({"error": "invalid_grant"}, status=400)), saved)

    assert saved.calls == []


def test_the_token_is_persisted_in_the_shape_the_client_reads() -> None:
    """Only the handshake changed; the vendor Context still loads this file."""
    saved = Saved()
    _authorize(Exchange(), saved)

    key, value = saved.calls[0]
    assert key == "auth"
    assert set(value) == {"client_id", "client_secret", "access_token", "access_token_expires", "refresh_token"}
    assert value["access_token"] == "at"
    assert value["refresh_token"] == "rt"


def test_an_expiry_is_stored_as_an_absolute_time() -> None:
    """`expires_in` is a duration; storing it raw would read as 1970."""
    saved = Saved()
    _authorize(Exchange(), saved)

    assert saved.calls[0][1]["access_token_expires"] > time.time()


# ── waiting for the real redirect ───────────────────────────────────────


def test_a_preconnect_does_not_end_the_handshake() -> None:
    """The bug this loop exists for.

    A browser opens speculative connections to a host it is about to visit, and
    the certificate interstitial opens its own. Handling exactly one connection
    treats the first of those as the answer and gives up a second in.
    """
    server = OneShotServer([(None, None), (None, None), ("the-code", None)])

    assert _capture(server) == "the-code"
    assert server.handled == 3
    assert server.closed


def test_waiting_is_bounded() -> None:
    """A closed tab must not hang the terminal, which serve_forever would."""
    server = OneShotServer()

    with pytest.raises(YahooLoginRequiredError):
        _capture(server, wait_seconds=0)
    assert server.closed


def test_a_refusal_is_reported_in_yahoos_own_words() -> None:
    with pytest.raises(YahooLoginRequiredError, match="user denied access"):
        _capture(OneShotServer([(None, "user denied access")]))


def test_the_socket_is_closed_even_when_the_code_arrives() -> None:
    """Otherwise port 8080 stays bound and the next login cannot start."""
    server = OneShotServer([("c", None)])

    _capture(server)

    assert server.closed


def test_a_rejected_scope_points_at_the_app_not_the_user() -> None:
    """Yahoo declines to issue a permission the app was never configured for.

    Every other refusal at this point is about the person or the request; this
    one is about a checkbox, so it must not read as "authorization failed".
    """
    with pytest.raises(YahooLoginRequiredError, match="does not have Fantasy Sports enabled"):
        _capture(OneShotServer([(None, "invalid scope")]))


def test_the_rejected_scope_is_quoted_back() -> None:
    with pytest.raises(YahooLoginRequiredError, match="'fspt-r'"):
        _capture(OneShotServer([(None, "invalid scope")]))
