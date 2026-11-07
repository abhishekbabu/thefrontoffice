"""This machine's Yahoo login, and the leagues it plays in.

Process-wide, unlike the per-league reader in `client.py`: one token serves every
league, and finding those leagues is the first thing done with it.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
from thefrontoffice.adapters.outbound.platforms.yahoo.client import (
    YahooContext,
    call,
    league_list,
    parse,
    readable,
    request,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError, YahooLoginRequiredError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague

logger = logging.getLogger(__name__)

LEAGUES_TTL = timedelta(hours=1)

Authorize = Callable[[str, str, str], None]
"""The interactive handshake: client id, client secret and redirect URI in, a token persisted."""


class YahooLeagueSource(Protocol):
    """How a provider finds the leagues it reads. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def find_leagues(self, game_code: str, season: int) -> list[YahooLeague]:
        """Every league the login plays in for one game and season."""
        ...


class YahooAuth:
    """Logs this machine in to Yahoo, and finds the leagues the login plays in."""

    def __init__(
        self,
        *,
        token_file: Path,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str,
        authorize: Authorize,
        connect: Callable[[], YahooContext],
        cache: JsonDiskCache,
        retry: RetryPolicy,
    ) -> None:
        """
        Args:
            token_file: where the handshake persists its token.
            authorize: runs the handshake; see `oauth.authorize`.
            connect: opens an SDK context on the persisted token.
        """
        self._token_file = token_file
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._authorize = authorize
        self._connect = connect
        self._cache = cache
        self._retry = retry

    def ensure_authorized(self) -> None:
        """Require a cached token without trying to obtain one.

        What every non-interactive caller wants. The handshake opens a browser
        and blocks until someone clicks it, so a server that attempted it would
        hang on a window nobody can see.

        Raises:
            YahooLoginRequiredError: no token has been cached yet.
        """
        if not self._token_file.exists():
            raise YahooLoginRequiredError()

    def login(self, force: bool = False) -> None:
        """Run the OAuth2 handshake. Interactive: opens a browser and waits.

        Raises:
            YahooAPIError: credentials are missing.
            YahooLoginRequiredError: the handshake did not complete.
        """
        if self._token_file.exists() and not force:
            return
        if not self._client_id or not self._client_secret:
            raise YahooAPIError("YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set before logging in.")

        self._authorize(self._client_id, self._client_secret, self._redirect_uri)
        logger.info("Yahoo login complete; token cached.")

    def context(self) -> YahooContext:
        """An authorized SDK context.

        Reports a missing token rather than starting the browser handshake: this
        runs inside a request handler as often as from a terminal.
        """
        self.ensure_authorized()
        return self._connect()

    def verify(self) -> None:
        """Confirm the cached token can actually read Fantasy Sports.

        A Yahoo authorization can succeed and still grant nothing: the library
        requests no scope, so Yahoo derives it from whatever API permissions the
        app had *at that moment*. The resulting token authenticates — Yahoo
        answers 403 rather than 401 — and is refused by every endpoint. A
        refresh cannot repair it either, because a refresh token carries the
        grant it was issued with.

        Cheap enough to run after every login, which is the only way to tell
        someone their fresh token is inert before they go looking elsewhere.

        Raises:
            YahooAuthError: the token carries no Fantasy Sports permission.
            YahooAPIError: Yahoo could not be reached.
        """
        context = self.context()
        call(self._retry, lambda: context.make_request("users;use_login=1/games"))

    def find_leagues(self, game_code: str, season: int) -> list[YahooLeague]:
        """Every league the login plays in for one game and season; none is an answer.

        Filters by game code and season rather than through the SDK's
        `get_leagues`, which resolves the season against a hardcoded table of
        Yahoo game keys and refuses any season newer than its last release —
        every October, until somebody publishes one.

        Raises:
            YahooLoginRequiredError: no token has been cached yet.
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        context = self.context()
        query = f"users;use_login=1/games;game_codes={game_code};seasons={season}/leagues"
        raw = self._cache.cached(
            f"leagues_{game_code}_{season}",
            LEAGUES_TTL,
            lambda: request(self._retry, lambda: context.make_request(query)),
        )
        # No game for the season (`<games count="0"/>`) and a game with no
        # leagues in it both mean the login plays nowhere.
        return readable("league list", lambda: league_list(parse(raw)["fantasy_content"]["users"]["user"]["games"]))
