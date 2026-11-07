"""The composition root: the one module that names concrete implementations.

Registers the competitions and wires engines to a model, and hands every entry
point the result as one `Wiring`. Everything else works against ports.

Every builder takes the settings it reads, so a test hands it its own rather
than patching the process's; an entry point that names none gets the
process's, which a save in Settings refreshes in place.

`is_configured` gates whether a platform is contacted at all — building a
provider can open an OAuth flow, and a user who does not play that competition
must never be made to sit through one.
"""

import functools
import logging
from collections.abc import Callable, Mapping
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
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import PROJECT_ROOT, AppSettings
from thefrontoffice.config.settings import settings as process_settings
from thefrontoffice.domain.errors import FrontOfficeError, NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.ports import (
    AccountLogin,
    AnalysisModel,
    AnswerStore,
    CompetitionProvider,
    ContextProvider,
    ForecastProvider,
    SeasonProvider,
    SubjectProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)

if TYPE_CHECKING:
    from thefrontoffice.adapters.outbound.cache import JsonDiskCache
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns, RoutedModel
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient
    from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient
    from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooAuth
    from thefrontoffice.adapters.outbound.storage.answers import DiskAnswerStore

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

    name: str
    """The competition alone, for where the platform goes without saying: 'NBA', 'Premier League'."""

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

    def blocker(self) -> FrontOfficeError | None:
        """What stands between this machine and using it, or None where it is ready.

        Configured is necessary, not sufficient: Yahoo also needs a login. An
        unconfigured entry is never probed, because its readiness check may look
        for a token it has no reason to have yet.
        """
        if not self.is_configured():
            return NotConfiguredError(self.label, self.requires)
        try:
            self.check_ready()
        except FrontOfficeError as e:
            return e
        return None

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
    from thefrontoffice.adapters.outbound.cache import JsonDiskCache

    return JsonDiskCache(Path(directory))


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


def _yahoo_auth(settings: AppSettings, cache: JsonDiskCache) -> YahooAuth:
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


def yahoo_auth(settings: AppSettings = process_settings) -> YahooAuth:
    """This machine's Yahoo login: for the entry points that log in and check the grant."""
    return _yahoo_auth(settings, _disk_cache(settings.yahoo_cache_dir))


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


def nfl_provider(settings: AppSettings = process_settings) -> SleeperNFLProvider:
    """The NFL provider, wired to the real clients: for the scripts that need its own methods, not just the port."""
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider(
        _configured(settings.sleeper_username, "nfl-sleeper"),
        client=_sleeper_client(settings),
        espn=_espn_client(settings),
    )


def _configured[T](value: T | None, key: str) -> T:
    """A setting an entry needs, as its gate checked it; asked for directly, the entry says what is missing.

    Raises:
        NotConfiguredError: it is unset — named as the entry's `requires` names it, so no provider repeats it.
    """
    if value is None or value == "":
        entry = REGISTRY.find(key)
        raise NotConfiguredError(entry.label, entry.requires)
    return value


def _nfl() -> type[SleeperNFLProvider]:
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider


def _fpl() -> type[FPLProvider]:
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider

    return FPLProvider


def _build_fpl(settings: AppSettings) -> FPLProvider:
    return _fpl()(_configured(settings.fpl_entry_id, "premier-league-fpl"), client=_fpl_client(settings))


def _nba() -> type[YahooNBAProvider]:
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider

    return YahooNBAProvider


def _build_nba(settings: AppSettings) -> YahooNBAProvider:
    """Deferred to here so that constructing the registry — which every entry point
    does at startup — never touches Yahoo. Building contacts nothing either: the
    provider finds its leagues when first asked, and an absent token is reported
    then rather than obtained, because the handshake opens a browser and this
    runs inside a request handler as often as not.
    """
    from thefrontoffice.adapters.outbound.competitions.nba.form import SleeperNBAForm
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient

    cache, retry = _disk_cache(settings.yahoo_cache_dir), _retry()
    auth = _yahoo_auth(settings, cache)
    sleeper = _sleeper_client(settings)
    return _nba()(
        auth=auth,
        yahoo_for=lambda league: YahooClient(league, context=auth.context(), cache=cache, retry=retry),
        nba=SleeperNBAForm(sleeper),
        sleeper=sleeper,
        max_weekly_adds=settings.yahoo_max_weekly_adds,
    )


def registry(settings: AppSettings) -> Registry:
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
                build=lambda: _build_nba(settings),
                is_configured=lambda: bool(settings.yahoo_client_id and settings.yahoo_client_secret),
                requires="YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
                # Yahoo also needs a cached token, which is a file this can just look for.
                check_ready=lambda: yahoo_auth(settings).ensure_authorized(),
            ),
            CompetitionEntry(
                sport="football",
                competition="nfl",
                platform="sleeper",
                label="NFL (Sleeper)",
                name="NFL",
                provider=_nfl,
                build=lambda: nfl_provider(settings),
                is_configured=lambda: bool(settings.sleeper_username),
                requires="SLEEPER_USERNAME",
            ),
            CompetitionEntry(
                sport="soccer",
                competition="premier-league",
                platform="fpl",
                label="FPL (Fantasy Premier League)",
                name="Premier League",
                provider=_fpl,
                build=lambda: _build_fpl(settings),
                is_configured=lambda: bool(settings.fpl_entry_id),
                requires="FPL_ENTRY_ID",
            ),
        )
    )


REGISTRY = registry(process_settings)
"""The process's registry, for the scripts that need no other part of the wiring."""


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


@dataclass(frozen=True)
class Wiring:
    """Everything an entry point is handed: the competitions, and the engines over them.

    Built once per process by `wiring()`; a test builds one from fakes. The
    model is built per call, so a key saved in Settings counts at once, and
    so is each login, so a client id saved there does too.
    """

    registry: Registry
    model: Callable[[], AnalysisModel]
    answers: AnswerStore
    decisions: ItemDecisions
    logins: Mapping[str, Callable[[], AccountLogin]]
    """Each platform that logs in through a browser, by its registry name."""

    env: EnvFile
    """The configuration, as the Settings page reads and edits it."""

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
            answers=self.answers,
            forecast=ForecastEngine(provider) if isinstance(provider, ForecastProvider) else None,
            season=SeasonEngine(provider) if isinstance(provider, SeasonProvider) else None,
        )


def wiring(settings: AppSettings = process_settings, env: Path = PROJECT_ROOT / ".env") -> Wiring:
    """The app as `settings` configure it: the registry, the model, and what is kept on disk.

    Args:
        env: the file `settings` were loaded from, which the Settings page edits.
    """
    return Wiring(
        registry=registry(settings),
        model=lambda: default_model(settings),
        answers=_answer_store(settings),
        decisions=_item_decisions(settings),
        logins={"yahoo": lambda: yahoo_auth(settings)},
        env=env_file(settings, env),
    )
