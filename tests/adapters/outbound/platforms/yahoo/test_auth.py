"""Tests for YahooAuth: this machine's Yahoo login, and finding the leagues it plays in."""

from pathlib import Path
from typing import Any

import pytest
import requests
from support.http import NO_WAIT, http_error

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooAuth
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooLoginRequiredError,
    YahooUnavailableError,
)

REDIRECT = "https://localhost:8080"


class FakeContext:
    """Stands in for yahoofantasy's Context, answering every request alike."""

    def __init__(self, response: str = "<fantasy_content/>", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []

    def make_request(self, query: str) -> str:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.response


class Authorizations:
    """Records each handshake instead of opening a browser."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.error = error

    def __call__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.calls.append((client_id, client_secret, redirect_uri))
        if self.error:
            raise self.error


def _auth(
    tmp_path: Path,
    *,
    token: bool = True,
    context: FakeContext | None = None,
    authorize: Authorizations | None = None,
    client_id: str | None = "the-id",
    client_secret: str | None = "the-secret",
) -> YahooAuth:
    token_file = tmp_path / ".yahoofantasy"
    if token:
        token_file.write_text("cached", encoding="utf-8")

    def _connect() -> Any:
        if context is None:
            pytest.fail("Yahoo was contacted")
        return context

    return YahooAuth(
        token_file=token_file,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT,
        authorize=authorize or Authorizations(),
        connect=_connect,
        cache=JsonDiskCache(tmp_path / "cache"),
        retry=NO_WAIT,
    )


# ── authorization is never obtained implicitly ──────────────────────────


def test_a_missing_token_is_reported_not_obtained(tmp_path: Path) -> None:
    """The handshake opens a browser and blocks. A server attempting it would
    wait on a window nobody can see."""
    authorize = Authorizations()

    with pytest.raises(YahooLoginRequiredError) as caught:
        _auth(tmp_path, token=False, authorize=authorize).ensure_authorized()
    assert caught.value.code == "yahoo_login_required"
    assert authorize.calls == []


def test_an_existing_token_satisfies_the_check(tmp_path: Path) -> None:
    _auth(tmp_path).ensure_authorized()  # does not raise


def test_a_context_is_never_opened_without_a_token(tmp_path: Path) -> None:
    """It runs inside a request handler as often as from a terminal."""
    authorize = Authorizations()

    with pytest.raises(YahooLoginRequiredError):
        _auth(tmp_path, token=False, authorize=authorize).context()
    assert authorize.calls == []


# ── login ───────────────────────────────────────────────────────────────


def test_an_existing_token_skips_the_login_flow(tmp_path: Path) -> None:
    authorize = Authorizations()
    _auth(tmp_path, authorize=authorize).login()
    assert authorize.calls == []


def test_force_logs_in_again_even_with_a_token(tmp_path: Path) -> None:
    authorize = Authorizations()
    _auth(tmp_path, authorize=authorize).login(force=True)
    assert len(authorize.calls) == 1


def test_login_passes_credentials_and_the_registered_redirect_uri(tmp_path: Path) -> None:
    """The redirect URI has to be the one registered on the Yahoo app, and the
    same one the token exchange later quotes back."""
    authorize = Authorizations()
    _auth(tmp_path, token=False, authorize=authorize).login()
    assert authorize.calls == [("the-id", "the-secret", REDIRECT)]


def test_missing_credentials_raise_rather_than_exit(tmp_path: Path) -> None:
    """Exiting the process is a terminal's idea of failure. Inside a server it
    takes down the request, and no inbound adapter gets to render anything."""
    with pytest.raises(YahooAPIError, match="must be set"):
        _auth(tmp_path, token=False, client_id=None, client_secret=None).login()


def test_a_failed_handshake_raises(tmp_path: Path) -> None:
    authorize = Authorizations(error=YahooLoginRequiredError())
    with pytest.raises(YahooLoginRequiredError):
        _auth(tmp_path, token=False, authorize=authorize).login()


# ── verifying a token really grants something ───────────────────────────


def test_verify_passes_when_yahoo_answers(tmp_path: Path) -> None:
    context = FakeContext()
    _auth(tmp_path, context=context).verify()
    assert context.queries == ["users;use_login=1/games"]


def test_a_token_that_authenticates_but_grants_nothing_is_caught(tmp_path: Path) -> None:
    """The failure this exists for.

    Yahoo answers 403 rather than 401, so the token is genuinely authenticated —
    it simply carries no scope, because the app had no API permissions saved
    when it was issued. Nothing downstream can tell that apart from a
    permissions problem, so it has to be caught at the login.
    """
    with pytest.raises(YahooAuthError) as caught:
        _auth(tmp_path, context=FakeContext(error=http_error(403))).verify()
    assert caught.value.code == "yahoo_not_approved"


def test_an_unreachable_yahoo_is_not_reported_as_a_permission_problem(tmp_path: Path) -> None:
    with pytest.raises(YahooUnavailableError):
        _auth(tmp_path, context=FakeContext(error=requests.exceptions.ConnectionError("no route"))).verify()


# ── find_leagues ────────────────────────────────────────────────────────


def _games(games: str) -> str:
    return f"<fantasy_content><users><user>{games}</user></users></fantasy_content>"


def _league(key: str, name: str) -> str:
    return f"<league><league_key>{key}</league_key><name>{name}</name></league>"


def test_leagues_are_looked_up_by_game_code_and_season(tmp_path: Path) -> None:
    """A season newer than the SDK's game-key table is still found: the query
    names the season instead of translating it into a key."""
    context = FakeContext(
        _games(f"<games><game><leagues>{_league('466.l.1', 'One')}{_league('466.l.2', 'Two')}</leagues></game></games>")
    )

    leagues = _auth(tmp_path, context=context).find_leagues("nba", 2031)

    assert context.queries == ["users;use_login=1/games;game_codes=nba;seasons=2031/leagues"]
    assert [(league.id, league.name) for league in leagues] == [("466.l.1", "One"), ("466.l.2", "Two")]
    assert all(league.ctx is context for league in leagues)


def test_a_single_league_is_not_mistaken_for_a_list(tmp_path: Path) -> None:
    context = FakeContext(_games(f"<games><game><leagues>{_league('466.l.1', 'Only')}</leagues></game></games>"))

    assert [league.name for league in _auth(tmp_path, context=context).find_leagues("nba", 2026)] == ["Only"]


@pytest.mark.parametrize(
    "games",
    ['<games count="0"/>', "<games><game><leagues/></game></games>", "<games><game/></games>"],
    ids=["no-game", "empty", "absent"],
)
def test_playing_in_no_league_is_an_empty_answer(tmp_path: Path, games: str) -> None:
    assert _auth(tmp_path, context=FakeContext(_games(games))).find_leagues("nba", 2026) == []


def test_the_league_list_is_served_from_cache_once_fetched(tmp_path: Path) -> None:
    context = FakeContext(_games(f"<games><game><leagues>{_league('466.l.1', 'One')}</leagues></game></games>"))
    auth = _auth(tmp_path, context=context)

    auth.find_leagues("nba", 2026)
    auth.find_leagues("nba", 2026)

    assert len(context.queries) == 1


def test_an_unapproved_app_fails_the_league_lookup_by_name(tmp_path: Path) -> None:
    with pytest.raises(YahooAuthError):
        _auth(tmp_path, context=FakeContext(error=http_error(403))).find_leagues("nba", 2026)


def test_an_unrecognized_league_list_raises(tmp_path: Path) -> None:
    context = FakeContext("<fantasy_content><error>?</error></fantasy_content>")

    with pytest.raises(YahooAPIError, match="unreadable league list"):
        _auth(tmp_path, context=context).find_leagues("nba", 2026)


def test_finding_leagues_without_a_token_never_contacts_yahoo(tmp_path: Path) -> None:
    with pytest.raises(YahooLoginRequiredError):
        _auth(tmp_path, token=False).find_leagues("nba", 2026)
