"""The composition root: the one module that names concrete implementations.

Registers the competitions and wires engines to a model, and hands every entry
point the result as one `Wiring`. Everything else works against ports.

`is_configured` gates whether a platform is contacted at all — building a
provider can open an OAuth flow, and a user who does not play that competition
must never be made to sit through one.
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from thefrontoffice.application.asking import AskEngine
from thefrontoffice.application.forecasting import ForecastEngine
from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.application.season import MarketEngine, SeasonEngine
from thefrontoffice.application.trading import TradeEngine
from thefrontoffice.application.week import WeekEngine
from thefrontoffice.application.wire import WireEngine
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.ports import (
    AccountLogin,
    AnalysisModel,
    AnswerStore,
    CompetitionProvider,
    ContextProvider,
    ForecastProvider,
    OutlookProvider,
    SeasonProvider,
    SubjectProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)

if TYPE_CHECKING:
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
    from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns, RoutedModel
    from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient
    from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient
    from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooAuth

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompetitionEntry:
    """One competition on one platform: everything that identifies it, and how to build it.

    Keyed by that pair rather than by the sport. Two things make the sport too
    coarse to identify an entry: one competition runs on several platforms —
    the NBA on Yahoo and on Sleeper, separate accounts and separate leagues —
    and one sport has several competitions, so college football beside the NFL
    would collide on `football-sleeper` and quietly lose one of them.

    The only place a competition's identity lives: its provider carries none,
    and what it can do is read off which ports its provider's class implements
    rather than declared beside them, so the two cannot disagree.
    """

    sport: str
    """The game itself: 'basketball', 'football', 'soccer'. For grouping the
    competitions that are the same sport; never an identity on its own."""

    competition: str
    """Which competition: 'nba', 'nfl', 'premier-league'."""

    platform: str
    """Where these fantasy leagues live: 'yahoo', 'sleeper', 'fpl'."""

    label: str
    """Human name for pickers and headers: 'NBA (Yahoo)'. Never a key."""

    provider: Callable[[], type[CompetitionProvider]]
    """The provider's class, imported only when asked, so listing competitions loads no SDK."""

    build: Callable[[], CompetitionProvider]
    is_configured: Callable[[], bool]
    requires: str
    """What to put in .env to enable it, quoted in the 'not configured' message."""

    check_ready: Callable[[], None] = lambda: None
    """Raise if the competition is configured but cannot be used yet.

    Separate from `is_configured` because credentials being present and a
    competition being usable are different questions — Yahoo needs an
    authorization on top of them, and offering one that will only fail is
    worse than greying it out. Must stay cheap and non-interactive: it runs on
    every page load.
    """

    @property
    def key(self) -> str:
        """What identifies this entry everywhere outside the registry, kept answers included.

        A competition alone is ambiguous once two platforms carry it, so every
        route, picker and stored scope uses the pair.
        """
        return f"{self.competition}-{self.platform}"

    def can(self, port: type[object]) -> bool:
        """Whether its provider implements `port`: read off the class, so nothing is built to ask."""
        return issubclass(self.provider(), port)

    @property
    def supports_trades(self) -> bool:
        """Whether a proposed trade can be evaluated."""
        return self.can(TradeProvider)

    @property
    def judges_wire(self) -> bool:
        """Whether its available players can be judged."""
        return self.can(WireProvider)

    @property
    def plans_ahead(self) -> bool:
        """Whether its coming weeks and the trades worth offering can be shown."""
        return self.can(OutlookProvider) and self.can(TradeMarketProvider)

    def open(self) -> CompetitionProvider:
        """Its provider, built — or why it cannot be, before anything is contacted.

        Raises:
            NotConfiguredError: this machine has no credentials for it.
        """
        if not self.is_configured():
            raise NotConfiguredError(self.label, self.requires)
        return self.build()

    def open_as[P](self, port: type[P], what: str) -> P:
        """Its provider, as the port a route needs — refused, unbuilt, where it has no such capability.

        Raises:
            UnsupportedError: its provider does not implement `port`.
            NotConfiguredError: this machine has no credentials for it.
        """
        if not self.can(port):
            raise UnsupportedError(self.label, what)
        return self.as_port(self.open(), port, what)

    def as_port[P](self, provider: CompetitionProvider, port: type[P], what: str) -> P:
        """`provider`, already built, as the port a caller needs.

        Raises:
            UnsupportedError: it does not implement `port`.
        """
        if not isinstance(provider, port):
            raise UnsupportedError(self.label, what)
        return provider


@dataclass(frozen=True)
class Registry:
    """Every competition the app knows, configured on this machine or not."""

    entries: tuple[CompetitionEntry, ...]

    def find(self, token: str) -> CompetitionEntry:
        """The entry a token names, by key or by competition alone.

        Typing "nba" stays meaningful while only one platform carries it, and
        becomes the first of them once two do — which is why anything that has
        to be unambiguous, like a route, uses the key.

        Raises:
            UnknownCompetitionError: nothing goes by that name.
        """
        name = token.lower().lstrip("/")
        found = next(
            (e for e in self.entries if e.key == name),
            next((e for e in self.entries if e.competition == name), None),
        )
        if found is None:
            raise UnknownCompetitionError(token)
        return found

    def configured(self) -> list[CompetitionEntry]:
        """Only the competitions this machine has credentials for."""
        return [entry for entry in self.entries if entry.is_configured()]


# ── platform transport ──────────────────────────────────────────────
# Every client gets its cache and its retry policy here, read from the settings
# as they stand when it is built, so a credential saved from the UI is seen by
# the next one.


def _disk_cache(directory: str) -> JsonDiskCache:
    from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache

    return JsonDiskCache(Path(directory))


def _retry() -> RetryPolicy:
    from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy

    return RetryPolicy()


def sleeper_client() -> SleeperClient:
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient

    return SleeperClient(cache=_disk_cache(settings.sleeper_cache_dir), retry=_retry())


def _espn_client() -> ESPNClient:
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient

    return ESPNClient(cache=_disk_cache(settings.espn_cache_dir), retry=_retry())


def _fpl_client() -> FPLClient:
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient

    return FPLClient(cache=_disk_cache(settings.fpl_cache_dir), retry=_retry())


def _yahoo_auth(cache: JsonDiskCache) -> YahooAuth:
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


def yahoo_auth() -> YahooAuth:
    """This machine's Yahoo login: for the entry points that log in and check the grant."""
    return _yahoo_auth(_disk_cache(settings.yahoo_cache_dir))


# What kept answers and decisions were filed under before they were keyed by
# `CompetitionEntry.key`: each competition's label as it then read. History,
# so spelled out rather than read off the entries, whose labels are free to change.
_FORMER_NAMES = {
    "nba-yahoo": "NBA (Yahoo)",
    "nfl-sleeper": "NFL (Sleeper)",
    "premier-league-fpl": "FPL (Fantasy Premier League)",
}


def _answer_store() -> DiskAnswerStore:
    from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore

    return DiskAnswerStore(_disk_cache(settings.answer_cache_dir), renamed=_FORMER_NAMES)


def _item_decisions() -> ItemDecisions:
    """The manager's decisions about to-do items, kept on this machine."""
    from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore

    return ItemDecisions(DiskItemStateStore(_disk_cache(settings.item_state_dir), renamed=_FORMER_NAMES))


# ── competitions ────────────────────────────────────────────────────


def nfl_provider() -> SleeperNFLProvider:
    """The NFL provider, wired to the real clients: for the scripts that need its own methods, not just the port."""
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider(settings.sleeper_username, client=sleeper_client(), espn=_espn_client())


def _nfl() -> type[SleeperNFLProvider]:
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider


def _check_yahoo_ready() -> None:
    """Yahoo also needs a cached token, which is a file this can just look for."""
    yahoo_auth().ensure_authorized()


def _fpl() -> type[FPLProvider]:
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider

    return FPLProvider


def _build_fpl() -> FPLProvider:
    return _fpl()(settings.fpl_entry_id, client=_fpl_client())


def _nba() -> type[YahooNBAProvider]:
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider

    return YahooNBAProvider


def _build_nba() -> YahooNBAProvider:
    """Yahoo needs an authorized context and a specific league object.

    Deferred to here so that constructing the registry — which every entry point
    does at startup — never touches Yahoo. Nothing in this path is interactive:
    an absent token is reported rather than obtained, because the handshake
    opens a browser and this runs inside a request handler as often as not.
    """
    from thefrontoffice.adapters.outbound.competitions.nba.form import SleeperNBAForm
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
    from thefrontoffice.domain.errors import LeagueNotFoundError

    provider = _nba()
    cache, retry = _disk_cache(settings.yahoo_cache_dir), _retry()
    leagues = _yahoo_auth(cache).find_leagues("nba", provider.season_year())
    if not leagues:
        raise LeagueNotFoundError("no Yahoo NBA leagues for this season")
    sleeper = sleeper_client()
    return provider(
        leagues[0],
        all_leagues=leagues,
        nba=SleeperNBAForm(sleeper),
        yahoo_for=lambda league: YahooClient(league, cache=cache, retry=retry),
        sleeper=sleeper,
        max_weekly_adds=settings.yahoo_max_weekly_adds,
    )


REGISTRY = Registry(
    (
        CompetitionEntry(
            sport="basketball",
            competition="nba",
            platform="yahoo",
            label="NBA (Yahoo)",
            provider=_nba,
            build=_build_nba,
            is_configured=lambda: bool(settings.yahoo_client_id and settings.yahoo_client_secret),
            requires="YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
            check_ready=_check_yahoo_ready,
        ),
        CompetitionEntry(
            sport="football",
            competition="nfl",
            platform="sleeper",
            label="NFL (Sleeper)",
            provider=_nfl,
            build=nfl_provider,
            is_configured=lambda: bool(settings.sleeper_username),
            requires="SLEEPER_USERNAME",
        ),
        CompetitionEntry(
            sport="soccer",
            competition="premier-league",
            platform="fpl",
            label="FPL (Fantasy Premier League)",
            provider=_fpl,
            build=_build_fpl,
            is_configured=lambda: bool(settings.fpl_entry_id),
            requires="FPL_ENTRY_ID",
        ),
    )
)


# ── models and engines ──────────────────────────────────────────────────


def default_model() -> RoutedModel:
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
        OpenAICompatibleClient(providers.groq()),
        OpenAICompatibleClient(providers.openrouter()),
    ]
    return RoutedModel(vendors, _cooldowns())


def ai_providers() -> list[str]:
    """The providers with a key, in the order they are tried."""
    return [vendor.name for vendor in default_model().configured()]


@functools.cache
def _cooldowns() -> Cooldowns:
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns

    return Cooldowns()


@dataclass(frozen=True)
class Wiring:
    """Everything an entry point is handed: the competitions, and the engines over them.

    Built once per process by `wiring()`; a test builds one from fakes. The
    model is built per call, so a key saved in Settings counts at once, and
    so is the Yahoo login, so a client id saved there does too.
    """

    registry: Registry
    model: Callable[[], AnalysisModel]
    answers: AnswerStore
    decisions: ItemDecisions
    yahoo_login: Callable[[], AccountLogin]

    def ai_available(self) -> bool:
        """Whether any model can be called at all.

        Read before offering anything that needs it. Without a key the app has
        no analysis to give, and the honest response is to not offer it — a
        button that explains why it cannot work is worse than no button.
        """
        return self.model().is_available

    def scout(self, entry: CompetitionEntry, provider: ContextProvider) -> ScoutEngine:
        """A scouting engine wired to the model and the judgments kept on disk."""
        return ScoutEngine(provider, key=entry.key, ai=self.model(), answers=self.answers)

    def ask(self, entry: CompetitionEntry, provider: SubjectProvider) -> AskEngine:
        """Questions about one thing on screen, wired like the scouting engine."""
        return AskEngine(provider, key=entry.key, ai=self.model(), answers=self.answers)

    def wire(self, entry: CompetitionEntry, provider: WireProvider) -> WireEngine:
        """Calls on available players, wired to the model."""
        return WireEngine(provider, key=entry.key, ai=self.model(), answers=self.answers)

    def trade(self, provider: TradeProvider) -> TradeEngine:
        """A trade engine wired to the model."""
        return TradeEngine(provider, ai=self.model())

    def market(self, provider: TradeMarketProvider) -> MarketEngine:
        """The trades worth offering, priced in playoff chance. Needs no model."""
        return MarketEngine(provider)

    def week(self, entry: CompetitionEntry, provider: CompetitionProvider) -> WeekEngine:
        """A competition's week, season and wire, with whichever generic engines it can feed."""
        return WeekEngine(
            provider,
            key=entry.key,
            decisions=self.decisions,
            forecast=ForecastEngine(provider) if isinstance(provider, ForecastProvider) else None,
            season=SeasonEngine(provider) if isinstance(provider, SeasonProvider) else None,
        )


def wiring() -> Wiring:
    """The app as this machine runs it: the registry, the configured model, and what is kept on disk."""
    return Wiring(
        registry=REGISTRY,
        model=default_model,
        answers=_answer_store(),
        decisions=_item_decisions(),
        yahoo_login=yahoo_auth,
    )
