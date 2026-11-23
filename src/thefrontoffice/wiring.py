"""The registry's types and the `Wiring` every entry point is handed.

Plain types, naming no concrete implementation: `bootstrap` builds them, an
entry point reads them, and a test builds them from fakes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from thefrontoffice.application.asking import AskEngine
from thefrontoffice.application.capabilities import CAPABILITIES
from thefrontoffice.application.forecasting import ForecastEngine
from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.application.season import MarketEngine, SeasonEngine
from thefrontoffice.application.trading import TradeEngine
from thefrontoffice.application.week import WeekEngine
from thefrontoffice.application.wire import WireEngine
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import AppSettings, env_var
from thefrontoffice.domain.errors import FrontOfficeError, NotConfiguredError, UnknownCompetitionError, UnsupportedError
from thefrontoffice.domain.ports import (
    AccountLogin,
    AnalysisModel,
    AnswerStore,
    BrowserCapture,
    CompetitionProvider,
    ContextProvider,
    ForecastProvider,
    SeasonProvider,
    SubjectProvider,
    TradeMarketProvider,
    TradeProvider,
    WireProvider,
)


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

    build: Callable[[CompetitionEntry], CompetitionProvider]
    """Its provider, built from the entry's settings; called by `open`, once `needs` are all set."""

    settings: AppSettings
    """What it is configured and built from, read when asked, so a value saved in Settings counts at once."""

    needs: tuple[str, ...] | Callable[[], tuple[str, ...]]
    """The settings fields it cannot run without, by field name — or how to read
    them off the settings as they stand, where another setting decides.

    Whether it is configured and what the 'not configured' message asks for
    are both read off these, so the two cannot name different settings.
    """

    week_word: str = "week"
    """What the competition calls a round, lowercase: 'gameweek' in FPL. The pages say it wherever they name one."""

    login: Callable[[], AccountLogin] | None = None
    """Its platform's browser login, where it has one: offered under the platform's name."""

    capture: Callable[[], BrowserCapture] | None = None
    """Its platform's browser sync, where it can be read that way: offered under the platform's name."""

    check_ready: Callable[[], None] = lambda: None
    """Raise if the competition is configured but cannot be used yet.

    Separate from `is_configured` because credentials being present and a
    competition being usable are different questions — Yahoo needs an
    authorization on top of them, and offering one that will only fail is
    worse than greying it out. Must stay cheap and non-interactive: it runs on
    every page load.
    """

    def needed(self) -> tuple[str, ...]:
        """The settings fields it needs as the settings stand now."""
        return self.needs() if callable(self.needs) else self.needs

    def is_configured(self) -> bool:
        """Whether every setting it needs is set."""
        return all(is_set(getattr(self.settings, field)) for field in self.needed())

    @property
    def requires(self) -> str:
        """What to put in .env to enable it, as the variables a user types: 'YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET'."""
        return " and ".join(env_var(field) for field in self.needed())

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
        return self.build(self)

    def refusal(self, port: type[object]) -> UnsupportedError:
        """Why it cannot do what `port` offers, worded once in `CAPABILITIES`."""
        return UnsupportedError(self.label, CAPABILITIES[port].refusal)

    def open_as[P](self, port: type[P]) -> P:
        """Its provider, as the port a route needs — refused, unbuilt, where it has no such capability.

        Raises:
            UnsupportedError: its provider does not implement `port`.
            NotConfiguredError: this machine has no credentials for it.
        """
        if not self.can(port):
            raise self.refusal(port)
        return self.as_port(self.open(), port)

    def as_port[P](self, provider: CompetitionProvider, port: type[P]) -> P:
        """`provider`, already built, as the port a caller needs.

        Raises:
            UnsupportedError: it does not implement `port`.
        """
        if not isinstance(provider, port):
            raise self.refusal(port)
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

    def by_key(self, key: str) -> CompetitionEntry:
        """The entry `key` names exactly: what a route addresses, where a bare competition would be ambiguous.

        Raises:
            UnknownCompetitionError: no entry has that key.
        """
        found = next((e for e in self.entries if e.key == key), None)
        if found is None:
            raise UnknownCompetitionError(key)
        return found

    def configured(self) -> list[CompetitionEntry]:
        """Only the competitions this machine has credentials for."""
        return [entry for entry in self.entries if entry.is_configured()]

    def logins(self) -> dict[str, Callable[[], AccountLogin]]:
        """Each platform that logs in through a browser, by the platform's name in its entries."""
        return {entry.platform: entry.login for entry in self.entries if entry.login is not None}

    def captures(self) -> dict[str, Callable[[], BrowserCapture]]:
        """Each platform that can be read from a browser sync, by the platform's name in its entries."""
        return {entry.platform: entry.capture for entry in self.entries if entry.capture is not None}


def is_set(value: object) -> bool:
    """Whether a setting holds a value: a blank one is as good as unset."""
    return value is not None and value != ""


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
    """Each platform that logs in through a browser, by the platform's name in its entries."""

    captures: Mapping[str, Callable[[], BrowserCapture]]
    """Each platform that can be read from a browser sync, by the platform's name in its entries."""

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
