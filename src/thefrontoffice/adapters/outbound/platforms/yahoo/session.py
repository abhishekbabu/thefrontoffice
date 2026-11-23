"""Yahoo read by this server from Yahoo's own frontend host, with the person's session cookie.

Yahoo's API refuses this app until Yahoo reviews it, but the read-only host
Yahoo's pages fetch from answers anyone carrying a signed-in session. The
person copies their Cookie header once; each read is then fetched from that
host by path — the same paths the browser capture plans, kept under the same
cache keys — and read by the same reader. No SDK is involved.

Undocumented and temporary, like the capture: the host is Yahoo's frontend's
and may change without notice. The cookie is a password in all but name, so it
goes out in the request header to Yahoo and nowhere else: no log line, error
or status carries it. What is kept of it is a short digest, to tell whether
the cookie Yahoo last refused is still the one set.
"""

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import timedelta
from http.cookiejar import DefaultCookiePolicy
from typing import Protocol

import requests

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.http import DEFAULT_TIMEOUT_SECONDS
from thefrontoffice.adapters.outbound.platforms.retry import DENIED, RetryPolicy
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.client import (
    LiveResponses,
    Refresh,
    YahooContext,
    call,
    leagues_in,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooSessionExpiredError
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import YahooRead
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.models import SessionStatus

logger = logging.getLogger(__name__)

SITE = "https://basketball.fantasysports.yahoo.com"
"""The page the frontend host expects its requests from."""

HEADERS = {
    "Accept": "application/xml, text/xml, */*",
    "Origin": SITE,
    "Referer": f"{SITE}/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
}
"""What a browser on a Yahoo Fantasy page sends beside its cookie."""

REFUSED = frozenset({301, 302, 303, 307, 308, 401, 403})
"""How the host turns away a session it no longer accepts: refused outright, or sent off to sign in."""

STATE = "session"
"""The entry recording how the last read with a cookie went. No Yahoo path has this shape."""


class Response(Protocol):
    status_code: int
    text: str

    @property
    def headers(self) -> Mapping[str, str]: ...

    def raise_for_status(self) -> None: ...


class HttpGet(Protocol):
    """The slice of a `requests` session the reader uses."""

    def get(self, url: str, *, headers: Mapping[str, str], timeout: int, allow_redirects: bool) -> Response: ...


def _cookieless() -> requests.Session:
    """A session that keeps no cookie Yahoo sets: the one sent is the one configured, and only that."""
    session = requests.Session()
    session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
    return session


def _denied(headers: Mapping[str, str]) -> requests.Response:
    """Yahoo's 999 as a `requests` response, so the retry policy reads its status and its `Retry-After`."""
    denied = requests.Response()
    denied.status_code = DENIED
    denied.headers.update(headers)
    return denied


def _digest(cookie: str) -> str:
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()[:16]


class SessionState:
    """Whether Yahoo last accepted the cookie now set, kept beside Yahoo's responses.

    Requests run on several threads, and the cache is written from one, so a
    request only notes how it went here and `record` writes it down afterwards.
    """

    def __init__(self, cache: DiskCache, cookie: str) -> None:
        self._cache = cache
        self._digest = _digest(cookie)
        self._answered = False
        self._refused = False

    def answered(self) -> None:
        self._answered = True

    def refused(self) -> None:
        self._refused = True

    def record(self) -> None:
        """Write down what the requests since the last record found, if they fetched anything at all."""
        if self._refused or self._answered:
            self._cache.set(STATE, {"cookie": self._digest, "expired": self._refused})
        self._answered = self._refused = False

    def status(self) -> SessionStatus:
        """How the last read with this cookie went; nothing known for a cookie never yet used."""
        hit = self._cache.lookup(STATE, timedelta.max)
        if hit is None or not isinstance(hit.value, dict) or hit.value.get("cookie") != self._digest:
            return SessionStatus()
        if hit.value.get("expired"):
            return SessionStatus(expired=True)
        return SessionStatus(fetched_at=hit.stored_at)

    def ensure_accepted(self) -> None:
        """Refuse a cookie Yahoo has already refused. Cheap: one file.

        Raises:
            YahooSessionExpiredError: Yahoo refused this cookie the last time it was sent.
        """
        if self.status().expired:
            raise YahooSessionExpiredError()


class YahooSession:
    """The transport the reader asks through, fetching each path from Yahoo's frontend host with the cookie."""

    def __init__(
        self, cookie: str, *, state: SessionState, http: HttpGet | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self._cookie = cookie
        self._state = state
        self._http = http or _cookieless()
        self._timeout = timeout

    def make_request(self, url: str, league: str | bool = False) -> str:
        """The raw XML Yahoo serves at `url`, below the league where one is named.

        Raises:
            YahooSessionExpiredError: Yahoo refused the cookie.
            requests.HTTPError: any other failure, for `call` to retry or translate — Yahoo's 999,
                its "too many requests", among them, though `requests` raises on no status past 599.
        """
        response = self._http.get(
            paths.FRONTEND + paths.served_at(url, league if isinstance(league, str) else ""),
            headers={**HEADERS, "Cookie": self._cookie},
            timeout=self._timeout,
            allow_redirects=False,
        )
        if response.status_code in REFUSED:
            self._state.refused()
            logger.warning(f"Yahoo refused the session cookie ({response.status_code}) for {url}")
            raise YahooSessionExpiredError()
        if response.status_code == DENIED:
            logger.warning(f"Yahoo asked for fewer requests ({DENIED}) for {url}")
            raise requests.HTTPError(f"{DENIED} Request denied for {url}", response=_denied(response.headers))
        response.raise_for_status()
        self._state.answered()
        return response.text


class SessionResponses:
    """Yahoo's answers fetched with the session, kept in the same cache under the same keys as a capture.

    `session` is a `YahooSession`, or one wrapped in the request budget, which is how bootstrap hands it over.
    """

    def __init__(
        self,
        session: YahooContext,
        *,
        state: SessionState,
        cache: DiskCache,
        retry: RetryPolicy,
        refresher: Refresh | None = None,
    ) -> None:
        self._session = session
        self._state = state
        self._cache = cache
        self._retry = retry
        self._live = LiveResponses(session, cache=cache, retry=retry, refresher=refresher)

    def raw(self, read: YahooRead) -> str:
        return self._recorded(lambda: self._live.raw(read))

    def many(self, reads: Mapping[str, YahooRead]) -> dict[str, str]:
        return self._recorded(lambda: self._live.many(reads))

    def forget(self, match: Callable[[str], bool]) -> int:
        return self._live.forget(match)

    def find_leagues(self, game_code: str, season: int) -> list[YahooLeague]:
        """Every league the session's login plays in for one game and season; none is an answer.

        Signed out, Yahoo answers a league list empty rather than refusing it,
        which would read as having no leagues — so before fetching one, the
        profile is asked for, which does refuse.

        Raises:
            YahooSessionExpiredError: Yahoo refused the cookie.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        read = paths.leagues(game_code, season)
        if self._cache.lookup(read.path, read.ttl) is None:
            self._recorded(lambda: call(self._retry, lambda: self._session.make_request(paths.PROFILE)))
        return leagues_in(self.raw(read))

    def _recorded[T](self, fetch: Callable[[], T]) -> T:
        try:
            return fetch()
        finally:
            self._state.record()
