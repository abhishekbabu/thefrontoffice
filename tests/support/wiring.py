"""A wiring of fakes, for the entry points: a registry over fake providers, a fake model, kept state in memory.

What `bootstrap.wiring()` builds from this machine's configuration, built
instead from stand-ins — so an inbound adapter's test hands its routes or
commands exactly what they read, and patches nothing.
"""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from support.ai import FakeAI
from support.stores import FakeAnswers, FakeItemStates
from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.bootstrap import CompetitionEntry, Registry, Wiring
from thefrontoffice.config.env_file import EnvFile
from thefrontoffice.config.settings import AppSettings
from thefrontoffice.domain.errors import PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import (
    CompetitionContext,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    Summary,
    TeamRef,
)
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, CompetitionProvider, LeagueRef

ABSENT = Path(__file__).with_name("absent.env")
"""A `.env` no test writes: configuration read from it is all defaults."""

LEAGUE = LeagueRef(league_id="L1", name="My League", detail="12-team")


class FakeCompetition:
    """Every `CompetitionProvider` method, answering with as little as it can.

    A test subclasses it and overrides what its route or command reads; what a
    competition can do beyond the base port is whatever methods the subclass
    adds, exactly as the registry reads a real provider.
    """

    leagues: tuple[LeagueRef, ...] = (LEAGUE,)

    def list_leagues(self) -> list[LeagueRef]:
        return list(self.leagues)

    def build_context(self, league_id: str) -> CompetitionContext:
        return CompetitionContext(prompt="prompt")

    def roster(self, league_id: str) -> list[PlayerCard]:
        return []

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        raise PlayerNotFoundError([player_id])

    def summary(self, league_id: str) -> Summary:
        return Summary()

    def schedule(self, league_id: str) -> LeagueSchedule:
        return LeagueSchedule()

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        return PlayerPage()

    def teams(self, league_id: str) -> list[TeamRef]:
        return []

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        raise TeamNotFoundError(team_id)


def entry(
    provider: CompetitionProvider,
    *,
    competition: str = "nfl",
    platform: str = "sleeper",
    label: str = "NFL (Sleeper)",
    name: str = "NFL",
    sport: str = "football",
    configured: bool = True,
    requires: str = "SLEEPER_USERNAME",
    check_ready: Callable[[], None] = lambda: None,
    built: list[int] | None = None,
) -> CompetitionEntry:
    """A registry entry whose provider is `provider`; each build appended to `built`, where given."""

    def build() -> CompetitionProvider:
        if built is not None:
            built.append(1)
        return provider

    return CompetitionEntry(
        sport=sport,
        competition=competition,
        platform=platform,
        label=label,
        name=name,
        provider=lambda: type(provider),
        build=build,
        is_configured=lambda: configured,
        requires=requires,
        check_ready=check_ready,
    )


class FakeLogin:
    """Stands in for a platform login: records each attempt, and fails with `error` where given.

    With `hold`, an attempt waits until the event is set — a handshake still
    waiting on its browser tab.
    """

    def __init__(
        self, error: Exception | None = None, hold: threading.Event | None = None, *, token: bool = False
    ) -> None:
        """
        Args:
            token: whether a token is kept from an earlier login.
        """
        self.error = error
        self.hold = hold
        self.token = token
        self.logins: list[bool] = []
        self.verified = threading.Event()

    def has_token(self) -> bool:
        return self.token

    def login(self, force: bool = False) -> None:
        self.logins.append(force)
        if self.hold is not None:
            self.hold.wait(timeout=5)

    def verify(self) -> None:
        if self.error is not None:
            raise self.error
        self.verified.set()


def wiring(
    *entries: CompetitionEntry,
    ai: AnalysisModel | None = None,
    answers: AnswerStore | None = None,
    states: FakeItemStates | None = None,
    login: FakeLogin | None = None,
    registry: Sequence[CompetitionEntry] = (),
    env: EnvFile | None = None,
) -> Wiring:
    """A wiring over `entries` (or a whole `registry`'s), with fakes for everything else."""
    model = ai or FakeAI()
    account = login or FakeLogin()
    return Wiring(
        registry=Registry(tuple(registry) or entries),
        model=lambda: model,
        answers=answers or FakeAnswers(),
        decisions=ItemDecisions(states or FakeItemStates()),
        logins={"yahoo": lambda: account},
        env=env or EnvFile(ABSENT, settings=AppSettings(_env_file=None)),
    )
