"""Tests for the Yahoo OAuth2 handshake.

The browser half cannot be exercised hermetically, so what is asserted here is
the half that was wrong: which parameters go out, and that the two halves agree
about the redirect URI.
"""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from thefrontoffice.adapters.outbound.platforms.yahoo import oauth
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError

REDIRECT = "https://localhost:8080"


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the token exchange without making one."""
    calls: list[dict[str, Any]] = []

    def _post(url: str, data: dict[str, Any], timeout: int = 0) -> FakeResponse:
        calls.append(data)
        return FakeResponse({"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "fspt-r"})

    monkeypatch.setattr(oauth.requests, "post", _post)
    return calls


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Capture what would be persisted, rather than writing a token file."""
    import yahoofantasy.util.persistence as persistence

    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(persistence, "save", lambda key, value, **kw: calls.append((key, value)))
    return calls


@pytest.fixture
def authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the browser, returning a code as though someone had clicked."""
    monkeypatch.setattr(oauth, "_capture_code", lambda redirect_uri, client_id, scope: "the-code")


# ── the bug this module exists for ──────────────────────────────────────


def test_the_exchange_quotes_back_the_same_redirect_uri(
    posted: list[dict[str, Any]], saved: list[Any], authorized: None
) -> None:
    """RFC 6749 §4.1.3 requires it, and Yahoo answers a mismatch with a token
    rather than an error — one that authenticates and grants nothing."""
    oauth.authorize("id", "secret", REDIRECT)

    assert posted[0]["redirect_uri"] == REDIRECT


def test_the_exchange_sends_an_authorization_code_grant(
    posted: list[dict[str, Any]], saved: list[Any], authorized: None
) -> None:
    oauth.authorize("id", "secret", REDIRECT)

    assert posted[0]["grant_type"] == "authorization_code"
    assert posted[0]["code"] == "the-code"
    assert posted[0]["client_id"] == "id"


def test_fantasy_read_is_requested_explicitly(
    monkeypatch: pytest.MonkeyPatch, posted: list[Any], saved: list[Any]
) -> None:
    """Leaving scope to be inferred is what makes an empty grant possible."""
    seen: list[str] = []
    monkeypatch.setattr(oauth, "_capture_code", lambda redirect_uri, client_id, scope: seen.append(scope) or "c")

    oauth.authorize("id", "secret", REDIRECT)

    assert seen == ["fspt-r"]


# ── the authorization request ───────────────────────────────────────────


class _Server:
    """Stands in for the callback server: nothing is bound, so no port is left open."""

    def __init__(self, *a: Any, **k: Any) -> None: ...

    socket = None

    def server_close(self) -> None: ...


def test_without_a_certificate_the_browser_is_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yahoo redirects to https, which nothing here could answer without one."""
    opened: list[str] = []
    monkeypatch.setattr(oauth.webbrowser, "open_new_tab", lambda url: opened.append(url))
    monkeypatch.setattr(oauth, "HTTPServer", _Server)
    monkeypatch.setattr(oauth, "_certificate", lambda: None)

    with pytest.raises(YahooLoginRequiredError):
        oauth._capture_code(REDIRECT, "the-id", "fspt-r")

    # No certificate means the server was never started, so nothing opened.
    assert opened == []


def test_the_url_is_built_from_the_same_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """Built here and quoted back in the exchange; they must not drift apart."""
    captured: dict[str, list[str]] = {}

    def _open(url: str) -> None:
        captured.update(parse_qs(urlparse(url).query))
        raise RuntimeError("stop before the wait")

    monkeypatch.setattr(oauth.webbrowser, "open_new_tab", _open)
    monkeypatch.setattr(oauth, "HTTPServer", _Server)

    with pytest.raises(RuntimeError):
        oauth._capture_code("http://localhost:9999", "the-id", "fspt-r")

    assert captured["redirect_uri"] == ["http://localhost:9999"]
    assert captured["client_id"] == ["the-id"]
    assert captured["scope"] == ["fspt-r"]
    assert captured["response_type"] == ["code"]


# ── failures ────────────────────────────────────────────────────────────


def test_a_refused_exchange_raises_rather_than_saving_nothing(
    monkeypatch: pytest.MonkeyPatch, saved: list[Any], authorized: None
) -> None:
    """Persisting a half-token would look authorized and fail on first use."""
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: FakeResponse({"error": "invalid_grant"}, status=400))

    with pytest.raises(YahooLoginRequiredError):
        oauth.authorize("id", "secret", REDIRECT)

    assert saved == []


def test_the_token_is_persisted_in_the_shape_the_client_reads(
    posted: list[Any], saved: list[tuple[str, dict[str, Any]]], authorized: None
) -> None:
    """Only the handshake changed; the vendor Context still loads this file."""
    oauth.authorize("id", "secret", REDIRECT)

    key, value = saved[0]
    assert key == "auth"
    assert set(value) == {"client_id", "client_secret", "access_token", "access_token_expires", "refresh_token"}
    assert value["access_token"] == "at"
    assert value["refresh_token"] == "rt"


def test_an_expiry_is_stored_as_an_absolute_time(
    posted: list[Any], saved: list[tuple[str, dict[str, Any]]], authorized: None
) -> None:
    """`expires_in` is a duration; storing it raw would read as 1970."""
    import time

    oauth.authorize("id", "secret", REDIRECT)

    assert saved[0][1]["access_token_expires"] > time.time()


# ── waiting for the real redirect ───────────────────────────────────────


class _OneShotServer:
    """Serves a scripted sequence of connections, one per handle_request."""

    timeout = None

    def __init__(self, arrivals: list[tuple[str | None, str | None]]) -> None:
        self.arrivals = list(arrivals)
        self.handled = 0
        self.closed = False

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


@pytest.fixture
def quiet_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth.webbrowser, "open_new_tab", lambda url: None)
    monkeypatch.setattr(oauth, "_certificate", lambda: None)


def _serve(monkeypatch: pytest.MonkeyPatch, arrivals: list[tuple[str | None, str | None]]) -> _OneShotServer:
    server = _OneShotServer(arrivals)
    monkeypatch.setattr(oauth, "HTTPServer", lambda *a, **k: server)
    oauth._Callback.code = oauth._Callback.error = None
    return server


def test_a_preconnect_does_not_end_the_handshake(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    """The bug this loop exists for.

    A browser opens speculative connections to a host it is about to visit, and
    the certificate interstitial opens its own. Handling exactly one connection
    treats the first of those as the answer and gives up a second in.
    """
    server = _serve(monkeypatch, [(None, None), (None, None), ("the-code", None)])

    assert oauth._capture_code("http://localhost:9999", "id", "fspt-r") == "the-code"
    assert server.handled == 3
    assert server.closed


def test_waiting_is_bounded(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    """A closed tab must not hang the terminal, which serve_forever would."""
    server = _serve(monkeypatch, [])
    monkeypatch.setattr(oauth, "CALLBACK_TIMEOUT_SECONDS", 0)

    with pytest.raises(YahooLoginRequiredError, match="No redirect arrived"):
        oauth._capture_code("http://localhost:9999", "id", "fspt-r")
    assert server.closed


def test_a_refusal_is_reported_in_yahoos_own_words(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    _serve(monkeypatch, [(None, "user denied access")])

    with pytest.raises(YahooLoginRequiredError, match="user denied access"):
        oauth._capture_code("http://localhost:9999", "id", "fspt-r")


def test_the_socket_is_closed_even_when_the_code_arrives(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    """Otherwise port 8080 stays bound and the next login cannot start."""
    server = _serve(monkeypatch, [("c", None)])

    oauth._capture_code("http://localhost:9999", "id", "fspt-r")

    assert server.closed


def test_a_rejected_scope_points_at_the_app_not_the_user(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    """Yahoo declines to issue a permission the app was never configured for.

    Every other refusal at this point is about the person or the request; this
    one is about a checkbox, so it must not read as "authorization failed".
    """
    _serve(monkeypatch, [(None, "invalid scope")])

    with pytest.raises(YahooLoginRequiredError, match="does not have Fantasy Sports enabled"):
        oauth._capture_code("http://localhost:9999", "id", "fspt-r")


def test_the_rejected_scope_is_quoted_back(monkeypatch: pytest.MonkeyPatch, quiet_browser: None) -> None:
    _serve(monkeypatch, [(None, "invalid scope")])

    with pytest.raises(YahooLoginRequiredError, match="'fspt-r'"):
        oauth._capture_code("http://localhost:9999", "id", "fspt-r")
