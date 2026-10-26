"""The composition root: the one module that names concrete implementations.

Registers the available sports and wires engines to a model. Everything else
works against ports.

`is_configured` gates whether a platform is contacted at all — building a
provider can open an OAuth flow, and a user who does not play that sport must
never be made to sit through one.
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from thefrontoffice.application.asking import AskEngine
from thefrontoffice.application.forecasting import ForecastEngine
from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.application.season import MarketEngine, SeasonEngine
from thefrontoffice.application.trading import TradeEngine
from thefrontoffice.application.wire import WireEngine
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.ports import (
    AnalysisModel,
    CompetitionProvider,
    ForecastProvider,
    SeasonProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)

if TYPE_CHECKING:
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompetitionEntry:
    """One competition on one platform.

    Keyed by that pair rather than by the sport. Two things make the sport too
    coarse to identify an entry: one competition runs on several platforms —
    the NBA on Yahoo and on Sleeper, separate accounts and separate leagues —
    and one sport has several competitions, so college football beside the NFL
    would collide on `football-sleeper` and quietly lose one of them.
    """

    sport: str
    """The game itself: 'basketball', 'football', 'soccer'. For grouping the
    competitions that are the same sport; never an identity on its own."""

    competition: str
    """Which competition: 'nba', 'nfl', 'premier-league'."""

    platform: str
    """Where these fantasy leagues live: 'yahoo', 'sleeper', 'fpl'."""

    label: str
    build: Callable[[], CompetitionProvider]
    is_configured: Callable[[], bool]
    requires: str
    """What to put in .env to enable it, quoted in the 'not configured' message."""

    check_ready: Callable[[], None] = lambda: None
    """Raise if the sport is configured but cannot be used yet.

    Separate from `is_configured` because credentials being present and a sport
    being usable are different questions — Yahoo needs an authorization on top
    of them, and offering a sport that will only fail is worse than greying it
    out. Must stay cheap and non-interactive: it runs on every page load.
    """

    # What the competition can do beyond the CompetitionProvider every one is.
    # Declared here rather than tested as `sport == "nba"` at each call site,
    # and because a client asks before any provider is built — building Yahoo's
    # touches the network. `tests/test_bootstrap.py` holds each to the ports
    # its provider actually implements, so the two cannot drift.

    supports_trades: bool = False
    """Whether a proposed trade can be evaluated: the provider is a TradeProvider."""

    judges_wire: bool = False
    """Whether its available players can be judged: the provider is a WireProvider."""

    plans_ahead: bool = False
    """Whether its coming weeks and trades worth offering can be shown: an OutlookProvider and a TradeMarketProvider."""

    @property
    def key(self) -> str:
        """What identifies this entry everywhere outside the registry.

        A competition alone is ambiguous once two platforms carry it, so every
        route, picker and stored preference uses the pair.
        """
        return f"{self.competition}-{self.platform}"


def nfl_provider() -> SleeperNFLProvider:
    """The NFL provider, wired to the real clients: for the scripts that need its own methods, not just the port."""
    from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
    from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient

    return SleeperNFLProvider(settings.sleeper_username, client=SleeperClient(), espn=ESPNClient())


def _build_nfl() -> CompetitionProvider:
    return nfl_provider()


def _check_yahoo_ready() -> None:
    """Yahoo also needs a cached token, which is a file this can just look for."""
    from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient

    YahooClient.ensure_authorized()


def _build_fpl() -> CompetitionProvider:
    from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
    from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLClient

    return FPLProvider(settings.fpl_entry_id, client=FPLClient())


def _build_nba() -> CompetitionProvider:
    """Yahoo needs an authorized context and a specific league object.

    Deferred to here so that constructing the registry — which every entry point
    does at startup — never touches Yahoo. Nothing in this path is interactive:
    an absent token is reported rather than obtained, because the handshake
    opens a browser and this runs inside a request handler as often as not.
    """
    from thefrontoffice.adapters.outbound.competitions.nba.form import SleeperNBAForm
    from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient
    from thefrontoffice.adapters.outbound.platforms.yahoo import client as yahoo
    from thefrontoffice.domain.errors import LeagueNotFoundError

    yahoo.YahooClient.ensure_authorized()
    ctx = yahoo.YahooClient.get_context()
    leagues = yahoo.YahooClient.find_leagues(ctx, "nba", YahooNBAProvider.season_year())
    if not leagues:
        raise LeagueNotFoundError("no Yahoo NBA leagues for this season")
    sleeper = SleeperClient()
    return YahooNBAProvider(
        leagues[0],
        all_leagues=leagues,
        nba=SleeperNBAForm(sleeper),
        yahoo_for=yahoo.YahooClient,
        sleeper=sleeper,
        max_weekly_adds=settings.yahoo_max_weekly_adds,
    )


REGISTRY: tuple[CompetitionEntry, ...] = (
    CompetitionEntry(
        sport="basketball",
        competition="nba",
        platform="yahoo",
        label="NBA (Yahoo)",
        build=_build_nba,
        is_configured=lambda: bool(settings.yahoo_client_id and settings.yahoo_client_secret),
        requires="YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
        check_ready=_check_yahoo_ready,
        supports_trades=True,
    ),
    CompetitionEntry(
        sport="football",
        competition="nfl",
        platform="sleeper",
        label="NFL (Sleeper)",
        build=_build_nfl,
        is_configured=lambda: bool(settings.sleeper_username),
        requires="SLEEPER_USERNAME",
        supports_trades=True,
        judges_wire=True,
        plans_ahead=True,
    ),
    CompetitionEntry(
        sport="soccer",
        competition="premier-league",
        platform="fpl",
        label="FPL (Fantasy Premier League)",
        build=_build_fpl,
        is_configured=lambda: bool(settings.fpl_entry_id),
        requires="FPL_ENTRY_ID",
        # FPL managers do not trade with each other; the equivalent move is a
        # transfer against the market, which the scouting report already covers.
        supports_trades=False,
    ),
)


def all_competitions() -> tuple[CompetitionEntry, ...]:
    return REGISTRY


def configured_competitions() -> list[CompetitionEntry]:
    """Only the sports this user has credentials for."""
    return [entry for entry in REGISTRY if entry.is_configured()]


def requirements_summary() -> str:
    """One line naming what to set for each sport, for a 'nothing configured' message."""
    return "; ".join(f"{e.label}: {e.requires}" for e in REGISTRY)


def find(key: str) -> CompetitionEntry | None:
    """The entry a token names, by pair or by sport alone.

    Typing "nba" stays meaningful while only one platform carries it, and
    becomes the first of them once two do — which is why anything that has to
    be unambiguous, like a route, uses the pair.
    """
    token = key.lower().lstrip("/")
    return next(
        (e for e in REGISTRY if e.key == token),
        next((e for e in REGISTRY if e.competition == token), None),
    )


# ── models and engines ──────────────────────────────────────────────────


def _models() -> list[tuple[str, AnalysisModel]]:
    """Every model provider, in the order they are preferred, configured or not.

    The single place a vendor is named. Imported lazily so that merely
    importing the composition root does not pull in an SDK. Gemini first: it
    alone enforces a response schema itself and grounds a trade in search.
    """
    from thefrontoffice.adapters.outbound.llm.gemini.client import GeminiClient
    from thefrontoffice.adapters.outbound.llm.openai_compatible import providers
    from thefrontoffice.adapters.outbound.llm.openai_compatible.client import OpenAICompatibleClient

    return [
        ("Gemini", GeminiClient()),
        ("Groq", OpenAICompatibleClient(providers.groq())),
        ("OpenRouter", OpenAICompatibleClient(providers.openrouter())),
    ]


def ai_providers() -> list[str]:
    """The providers with a key, in the order they are tried."""
    return [name for name, model in _models() if getattr(model, "is_available", False)]


def default_model() -> AnalysisModel:
    """Every configured provider as one model, failing over between them.

    Built per call, so a key saved in Settings counts at once; the cooldowns
    are the process's, so a provider out of quota stays rested across requests.
    """
    from thefrontoffice.adapters.outbound.llm.routing import RoutedModel

    return RoutedModel(_models(), _cooldowns())


@functools.cache
def _cooldowns() -> Cooldowns:
    from thefrontoffice.adapters.outbound.llm.routing import Cooldowns

    return Cooldowns()


def ai_available() -> bool:
    """Whether any model can be called at all.

    Read before offering anything that needs it. Without a key the app has no
    analysis to give, and the honest response is to not offer it — a button
    that explains why it cannot work is worse than no button.
    """
    return bool(ai_providers())


def scout_engine(provider: CompetitionProvider) -> ScoutEngine:
    """A scouting engine wired to the configured model and the judgments kept on disk."""
    from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore

    return ScoutEngine(provider, ai=default_model(), answers=DiskAnswerStore())


def forecast_engine(provider: ForecastProvider) -> ForecastEngine:
    """A provider's matchup, simulated. Needs no model and no key."""
    return ForecastEngine(provider)


def season_engine(provider: SeasonProvider) -> SeasonEngine:
    """A provider's regular season, simulated to the playoffs. Needs no model either."""
    return SeasonEngine(provider)


def market_engine(provider: TradeMarketProvider) -> MarketEngine:
    """The trades worth offering, priced in playoff chance. Needs no model either."""
    return MarketEngine(provider)


def item_decisions() -> ItemDecisions:
    """The manager's decisions about to-do items, kept on this machine."""
    from thefrontoffice.adapters.outbound.storage.items import DiskItemStateStore

    return ItemDecisions(DiskItemStateStore())


def ask_engine(provider: CompetitionProvider) -> AskEngine:
    """Questions about one thing on screen, wired like the scouting engine."""
    from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore

    return AskEngine(provider, ai=default_model(), answers=DiskAnswerStore())


def wire_engine(provider: WireProvider) -> WireEngine:
    """Calls on available players, wired to the configured model."""
    from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore

    return WireEngine(provider, ai=default_model(), answers=DiskAnswerStore())


def trade_engine(provider: TradeProvider) -> TradeEngine:
    """A trade engine wired to the configured model."""
    return TradeEngine(provider, ai=default_model())
