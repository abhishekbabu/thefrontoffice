"""The composition root: the one module that names concrete implementations.

Registers the competitions and wires engines to a model, and hands every entry
point the result as one `Wiring` (the types live in `wiring`; this module only
assembles them). Everything else works against ports.

Every builder takes the settings it reads, so a test hands it its own rather
than patching the process's; an entry point that names none gets the
process's, which a save in Settings refreshes in place.

Each entry names the settings it cannot run without, and whether it is
configured and what the "not configured" message asks for are both read off
them. That gate decides whether a platform is built at all: a user who does
not play a competition never has its provider built, nor a readiness check
look for a login they have no reason to have.
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING

from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import PROJECT_ROOT, AppSettings
from thefrontoffice.config.settings import settings as process_settings
from thefrontoffice.domain.errors import NotConfiguredError
from thefrontoffice.domain.ports import OddsTuning
from thefrontoffice.wiring import CompetitionEntry, Registry, Wiring, is_set

if TYPE_CHECKING:
    from thefrontoffice.adapters.outbound.cache import DiskCache
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns, RoutedModel
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient
    from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient
    from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooAuth
    from thefrontoffice.adapters.outbound.platforms.yahoo.budget import Breaker, Budget, Refresher
    from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooCapture
    from thefrontoffice.adapters.outbound.platforms.yahoo.paths import ScoreboardPace
    from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionState
    from thefrontoffice.adapters.outbound.storage.answers import DiskAnswerStore

logger = logging.getLogger(__name__)


# ── platform transport ──────────────────────────────────────────────
# Every client gets its cache and its retry policy here, read from the settings
# as they stand when it is built, so a credential saved from the UI is seen by
# the next one.


def _disk_cache(directory: str) -> DiskCache:
    from thefrontoffice.adapters.outbound.cache import DiskCache

    return DiskCache(Path(directory))


def _retry() -> RetryPolicy:
    from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy

    return RetryPolicy()


def _sleeper_client(settings: AppSettings) -> SleeperClient:
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient

    return SleeperClient(cache=_disk_cache(settings.sleeper_cache_dir), retry=_retry())


def _espn_client(settings: AppSettings) -> ESPNClient:
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient

    return ESPNClient(cache=_disk_cache(settings.espn_cache_dir), retry=_retry())


def _fpl_client(settings: AppSettings) -> FPLClient:
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient

    return FPLClient(cache=_disk_cache(settings.fpl_cache_dir), retry=_retry())


def _yahoo_auth(settings: AppSettings, cache: DiskCache) -> YahooAuth:
    from yahoofantasy import Context

    from thefrontoffice.adapters.outbound.platforms.yahoo import oauth
    from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooAuth

    return YahooAuth(
        token_file=Path(settings.yahoo_token_file),
        client_id=settings.yahoo_client_id,
        client_secret=settings.yahoo_client_secret,
        redirect_uri=settings.yahoo_redirect_uri,
        authorize=oauth.authorize,
        connect=Context,
        cache=cache,
        retry=_retry(),
    )


def odds_tuning(settings: AppSettings = process_settings) -> OddsTuning:
    """The fit behind a basketball category league's odds, read from Sleeper alone: no league or login needed."""
    from thefrontoffice.adapters.outbound.competitions.nba.tuning import NBAOddsTuning

    client = _sleeper_client(settings)
    return NBAOddsTuning(games=client, projections=client)


def yahoo_auth(settings: AppSettings = process_settings) -> YahooAuth:
    """This machine's Yahoo login: for the entry points that log in and check the grant."""
    return _yahoo_auth(settings, _disk_cache(settings.yahoo_cache_dir))


def _yahoo_session(settings: AppSettings, cache: DiskCache) -> SessionState | None:
    """How reading with the session cookie is going, where Yahoo is read that way and a cookie is set."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionState

    cookie = settings.yahoo_session_cookie
    return SessionState(cache, cookie) if settings.yahoo_source == "session" and cookie else None


# Yahoo is asked within one budget per host for the whole process, whichever
# request handler builds the reader: a pace shared by nothing is no pace.


@functools.cache
def _yahoo_budget(host: str) -> Budget:
    from thefrontoffice.adapters.outbound.platforms.yahoo.budget import Budget

    return Budget()


@functools.cache
def _yahoo_breaker(host: str, credential: str) -> Breaker:
    """One breaker per credential, so pasting a fresh cookie is not held up by the pause the old one earned."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.budget import Breaker

    return Breaker()


def _yahoo_budget_for(host: str, credential: str) -> Budget:
    return replace(_yahoo_budget(host), breaker=_yahoo_breaker(host, credential))


@functools.cache
def _yahoo_refresher(cache_dir: str) -> Refresher:
    from thefrontoffice.adapters.outbound.platforms.yahoo.budget import Refresher

    return Refresher(lambda: _disk_cache(cache_dir))


NBA_GAME_HOURS = ("09:00", "01:00")
"""When an NBA game can be on, Pacific: the earliest weekend tip-off to the last West Coast final whistle."""


def _nba_pace(games_on: Callable[[date], bool]) -> ScoreboardPace:
    """When an NBA league's scoreboard can be moving: inside game hours, on a day the schedule has games."""
    from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC
    from thefrontoffice.adapters.outbound.platforms.yahoo.paths import ScoreboardPace

    opens, closes = (time.fromisoformat(hour) for hour in NBA_GAME_HOURS)
    return ScoreboardPace(PACIFIC, opens, closes, games_on=games_on)


def _yahoo_capture(settings: AppSettings) -> YahooCapture:
    """Yahoo as the sync bookmark captured it, into the cache the live reader keeps its responses in."""
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YAHOO_GAME
    from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooCapture

    cache = _disk_cache(settings.yahoo_cache_dir)
    return YahooCapture(
        cache,
        games=(YAHOO_GAME,),
        active=settings.yahoo_source == "browser",
        session=_yahoo_session(settings, cache),
    )


YAHOO_CREDENTIALS = ("yahoo_client_id", "yahoo_client_secret")


def _yahoo_needs(settings: AppSettings) -> tuple[str, ...]:
    """Yahoo's OAuth app credentials, which the browser sync has no use for, or the session cookie."""
    match settings.yahoo_source:
        case "browser":
            return ()
        case "session":
            return ("yahoo_session_cookie",)
        case _:
            return YAHOO_CREDENTIALS


def _yahoo_ready(settings: AppSettings) -> None:
    """A sync recent enough to read in browser mode; a cookie Yahoo has not refused in session mode;
    a cached token otherwise, which is a file this can just look for."""
    match settings.yahoo_source:
        case "browser":
            _yahoo_capture(settings).ensure_captured()
        case "session":
            session = _yahoo_session(settings, _disk_cache(settings.yahoo_cache_dir))
            if session is not None:
                session.ensure_accepted()
        case _:
            yahoo_auth(settings).ensure_authorized()


def env_file(settings: AppSettings = process_settings, path: Path = PROJECT_ROOT / ".env") -> EnvFile:
    """The `.env` at `path`, which `settings` were loaded from and a save reloads them from."""
    return EnvFile(path, settings=settings)


def _answer_store(settings: AppSettings) -> DiskAnswerStore:
    from thefrontoffice.adapters.outbound.storage.answers import DiskAnswerStore

    return DiskAnswerStore(_disk_cache(settings.answer_cache_dir))


def _item_decisions(settings: AppSettings) -> ItemDecisions:
    """The manager's decisions about to-do items, kept on this machine."""
    from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore

    return ItemDecisions(DiskItemStateStore(_disk_cache(settings.item_state_dir)))


# ── competitions ────────────────────────────────────────────────────


def _required[T](value: T | None, entry: CompetitionEntry) -> T:
    """A setting `entry` needs, which its gate has already checked; narrowed here for the builder that reads it.

    Raises:
        NotConfiguredError: it is unset after all — a builder called without the gate.
    """
    if value is None or not is_set(value):
        raise NotConfiguredError(entry.label, entry.requires)
    return value


def _nfl() -> type[SleeperNFLProvider]:
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider


def _fpl() -> type[FPLProvider]:
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider

    return FPLProvider


def _build_nfl(entry: CompetitionEntry) -> SleeperNFLProvider:
    settings = entry.settings
    return _nfl()(
        _required(settings.sleeper_username, entry),
        client=_sleeper_client(settings),
        espn=_espn_client(settings),
    )


def _build_fpl(entry: CompetitionEntry) -> FPLProvider:
    return _fpl()(_required(entry.settings.fpl_entry_id, entry), client=_fpl_client(entry.settings))


def _nba() -> type[YahooNBAProvider]:
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider

    return YahooNBAProvider


def _build_nba(entry: CompetitionEntry) -> YahooNBAProvider:
    """Building contacts nothing: the provider finds its leagues when first asked,
    and an absent token is reported then rather than obtained, because the
    handshake opens a browser and this runs inside a request handler as often
    as not.
    """
    from thefrontoffice.adapters.outbound.competitions.nba.form import SleeperNBAForm
    from thefrontoffice.adapters.outbound.competitions.nba.week import SleeperNBASchedule
    from thefrontoffice.adapters.outbound.platforms.yahoo import paths
    from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooLeagueSource
    from thefrontoffice.adapters.outbound.platforms.yahoo.budget import BudgetedContext
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import LiveResponses, YahooClient, YahooResponses
    from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionResponses, SessionState, YahooSession

    settings = entry.settings
    leagues: YahooLeagueSource
    responses: Callable[[], YahooResponses]
    refresher = _yahoo_refresher(settings.yahoo_cache_dir)
    if settings.yahoo_source == "browser":
        capture = _yahoo_capture(settings)
        leagues, responses = capture, lambda: capture
    elif settings.yahoo_source == "session":
        cache, cookie = _disk_cache(settings.yahoo_cache_dir), _required(settings.yahoo_session_cookie, entry)
        state = SessionState(cache, cookie)
        budgeted = BudgetedContext(YahooSession(cookie, state=state), _yahoo_budget_for(paths.FRONTEND, cookie))
        session = SessionResponses(budgeted, state=state, cache=cache, retry=_retry(), refresher=refresher)
        leagues, responses = session, lambda: session
    else:
        cache, retry = _disk_cache(settings.yahoo_cache_dir), _retry()
        auth = _yahoo_auth(settings, cache)
        leagues, responses = (
            auth,
            lambda: LiveResponses(
                BudgetedContext(auth.context(), _yahoo_budget_for(paths.API, settings.yahoo_client_id or "")),
                cache=cache,
                retry=retry,
                refresher=refresher,
            ),
        )
    sleeper = _sleeper_client(settings)
    schedule = SleeperNBASchedule(sleeper)
    pace = _nba_pace(lambda day: bool(schedule.games_between(day, day)))
    return _nba()(
        auth=leagues,
        yahoo_for=lambda league: YahooClient(league, responses=responses(), pace=pace),
        form=SleeperNBAForm(sleeper),
        games=schedule,
        sleeper=sleeper,
        espn=_espn_client(settings),
        fallback_weekly_adds=settings.yahoo_max_weekly_adds,
    )


def registry(settings: AppSettings = process_settings) -> Registry:
    """Every competition, configured and built from `settings` as they stand when asked."""
    return Registry(
        (
            CompetitionEntry(
                sport="basketball",
                competition="nba",
                platform="yahoo",
                label="NBA (Yahoo)",
                name="NBA",
                provider=_nba,
                build=_build_nba,
                settings=settings,
                needs=lambda: _yahoo_needs(settings),
                login=lambda: yahoo_auth(settings),
                capture=lambda: _yahoo_capture(settings),
                check_ready=lambda: _yahoo_ready(settings),
            ),
            CompetitionEntry(
                sport="football",
                competition="nfl",
                platform="sleeper",
                label="NFL (Sleeper)",
                name="NFL",
                provider=_nfl,
                build=_build_nfl,
                settings=settings,
                needs=("sleeper_username",),
            ),
            CompetitionEntry(
                sport="soccer",
                competition="premier-league",
                platform="fpl",
                label="FPL (Fantasy Premier League)",
                name="Premier League",
                provider=_fpl,
                build=_build_fpl,
                settings=settings,
                needs=("fpl_entry_id",),
                week_word="gameweek",
            ),
        )
    )


# ── models and engines ──────────────────────────────────────────────────


def default_model(settings: AppSettings = process_settings) -> RoutedModel:
    """Every model provider as one model, failing over between them in the order they are preferred.

    The single place a vendor is chosen. Imported lazily so that merely
    importing the composition root does not pull in an SDK. Gemini first: it
    alone enforces a response schema itself and grounds a trade in search.

    Built per call, so a key saved in Settings counts at once; the cooldowns
    are the process's, so a provider out of quota stays rested across requests.
    """
    from thefrontoffice.adapters.outbound.llm.gemini import client as gemini
    from thefrontoffice.adapters.outbound.llm.openai_compatible import providers
    from thefrontoffice.adapters.outbound.llm.openai_compatible.client import OpenAICompatibleClient
    from thefrontoffice.adapters.outbound.llm.routing import RoutedModel

    vendors = [
        gemini.GeminiClient(client=gemini.connect(settings.gemini_api_key)),
        OpenAICompatibleClient(providers.groq(settings)),
        OpenAICompatibleClient(providers.openrouter(settings)),
    ]
    return RoutedModel(vendors, _cooldowns())


def ai_providers(settings: AppSettings = process_settings) -> list[str]:
    """The providers with a key, in the order they are tried."""
    return [vendor.name for vendor in default_model(settings).configured()]


@functools.cache
def _cooldowns() -> Cooldowns:
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns

    return Cooldowns()


def wiring(settings: AppSettings = process_settings, env: Path = PROJECT_ROOT / ".env") -> Wiring:
    """The app as `settings` configure it: the registry, the model, and what is kept on disk.

    Args:
        env: the file `settings` were loaded from, which the Settings page edits.
    """
    competitions = registry(settings)
    return Wiring(
        registry=competitions,
        model=lambda: default_model(settings),
        answers=_answer_store(settings),
        decisions=_item_decisions(settings),
        logins=competitions.logins(),
        captures=competitions.captures(),
        env=env_file(settings, env),
    )
