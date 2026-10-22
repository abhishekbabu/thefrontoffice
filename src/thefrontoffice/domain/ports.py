"""The interfaces the core depends on.

Ports live with the code that *uses* them, not with the code that implements
them. That is what keeps the dependency arrows pointing inward: the domain names
what it needs, and the adapters satisfy it. Nothing in this package imports an
adapter.
"""

from dataclasses import dataclass
from typing import Protocol, TypedDict, TypeVar, runtime_checkable

from pydantic import BaseModel

from thefrontoffice.domain.models import (
    CompetitionContext,
    ItemState,
    LeagueSchedule,
    MatchupInput,
    PlayedMatchup,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    Remembered,
    Summary,
    TeamRef,
    TradeProposal,
)

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True)
class LeagueRef:
    """A league the user is in, in whatever platform the competition uses."""

    league_id: str
    name: str
    competition: str
    detail: str = ""
    """Anything worth showing beside the name — record, scoring format, team count."""

    url: str = ""
    """This league on its own platform. Reading it here is the whole app; the
    moves themselves are made there, so every view offers the way across.
    Empty where a platform has no addressable page for it."""


class HistoryTurn(TypedDict):
    """One turn of a seeded conversation.

    Defined here rather than in the LLM adapter because the engines construct
    these when they seed a follow-up chat, and the port has to name the same
    shape the adapter accepts.
    """

    role: str
    parts: list[str]


class AnswerStore(Protocol):
    """Where every model answer is kept between requests, one per scope."""

    def latest(self, scope: str, schema: type[TModel]) -> Remembered[TModel] | None:
        """The last answer kept for `scope`, read as `schema`; None where there is none recent enough."""
        ...

    def save(self, scope: str, remembered: Remembered[TModel]) -> None: ...


class ItemStateStore(Protocol):
    """Where the manager's decisions about to-do items are kept, per league."""

    def states(self, scope: str) -> dict[str, ItemState]:
        """Every kept decision for `scope`, keyed by item key."""
        ...

    def save(self, scope: str, states: dict[str, ItemState]) -> None: ...


class ChatSession(Protocol):
    """An open conversation, for follow-up questions about a finished report."""

    def send_message(self, message: str) -> object: ...


@runtime_checkable
class AnalysisModel(Protocol):
    """The language model the engines talk to.

    Named as a capability rather than a vendor so the core never imports
    `clients.gemini`. Swapping models, or standing one up in a test, means
    satisfying this and nothing else.
    """

    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        """Return a response validated against `schema`."""
        ...

    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        """Convert prose the model already produced into `schema`."""
        ...

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        """Open a conversation, optionally seeded with prior turns."""
        ...

    def parse_trade_string(self, text: str) -> TradeProposal:
        """Parse a natural-language trade into the two sides."""
        ...


@runtime_checkable
class CompetitionProvider(Protocol):
    """One competition on one platform.

    A competition rather than a sport, because that is what a fantasy game is
    played over: the NBA, the NFL, the Premier League. One sport can have
    several — college football beside the NFL — and each is its own provider
    with its own rules, so the sport is an attribute rather than the identity.
    """

    sport: str
    """The game itself: 'basketball', 'football', 'soccer'. Groups competitions
    that are the same sport; never identifies one on its own."""

    competition: str
    """Which competition this provides: 'nba', 'nfl', 'premier-league'."""

    label: str
    """Human name for pickers: 'NBA (Yahoo)'."""

    def list_leagues(self) -> list[LeagueRef]:
        """Every league this user plays in for the current season.

        Raises:
            FrontOfficeError: the platform is unreachable or unconfigured.
        """
        ...

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather this league's state and render the scouting prompt.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The user's roster, one card per player, for a team view.

        Cheaper than build_context — a roster listing should not pull a waiver
        pool — and richer than a lineup, which shows only what a week turns on.
        """
        ...

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """Everything worth knowing about one player.

        Raises:
            PlayerNotFoundError: nothing in this league has that identifier.
        """
        ...

    def summary(self, league_id: str) -> Summary:
        """Where this team stands, without producing an analysis.

        The same figures a finished report carries in its header, available
        before one is asked for — a page that shows nothing until a model has
        been called is empty for the whole time it takes to call one, and every
        number here is already known.

        Cheaper than build_context: no candidate pool, no market, no model.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """One window onto the players nobody in this league has, best first.

        The other half of a roster: what you hold is only half the question,
        and the half that changes is what is still out there. Columns are the
        competition's own, exactly as `roster` returns them, so one table renders
        both.

        A page rather than a list because a football pool is four thousand
        players — which also means the ordering has to happen here, where the
        whole list is, rather than in a client holding fifty rows of it.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, so their rosters can be opened.

        Raises:
            FrontOfficeError: the league is missing.
        """
        ...

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own.

        Raises:
            TeamNotFoundError: no team in this league has that identifier.
        """
        ...

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The league beyond this week: the season, the table, the real games.

        Separate from `summary` because it is a different question asked at a
        different time — how the season is going, rather than what to do about
        Sunday — and it costs requests that the week does not need.

        Every section is optional. A platform that has no transaction feed
        returns none rather than an empty promise.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...


@runtime_checkable
class TradeProvider(Protocol):
    """A competition that can also evaluate trades.

    Separate from CompetitionProvider because trade support arrives per
    competition: a
    provider can scout without yet being able to price a trade, and the registry
    advertises which can via `supports_trades`.
    """

    sport: str
    label: str

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Resolve both sides of the trade and render the evaluation prompt.

        Raises:
            PlayerNotFoundError: a named player could not be resolved. Silently
                dropping one would evaluate a different trade than was asked.
        """
        ...


@runtime_checkable
class WireProvider(Protocol):
    """A competition that can have its available players judged.

    Separate from CompetitionProvider for the reason TradeProvider is: the
    capability arrives per competition, and the registry advertises which
    have it via `judges_wire`.
    """

    sport: str
    label: str

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        """Render the prompt asking for one call per listed available player.

        Raises:
            PlayerNotFoundError: an id is not an available player here.
        """
        ...


@runtime_checkable
class ForecastProvider(Protocol):
    """A competition whose matchup can be simulated.

    It supplies the inputs — each player's range, whether he plays, what is
    already on the board, which lineup moves to price — and the generic
    engine does the rest, so a new competition is a provider, not a new engine.
    """

    label: str

    def matchup_input(self, league_id: str) -> MatchupInput | None:
        """This week's matchup, ready to simulate; None where there is no opponent."""
        ...

    def played_matchups(self, league_id: str, week: int) -> list[PlayedMatchup]:
        """Every matchup of a week already played, as it stood before kickoff, with the result."""
        ...
