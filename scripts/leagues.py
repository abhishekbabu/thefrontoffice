"""The competition and league a script runs over, chosen the same way by each."""

from thefrontoffice.bootstrap import CompetitionEntry, Registry
from thefrontoffice.domain.errors import LeagueNotFoundError
from thefrontoffice.domain.ports import CompetitionProvider, LeagueRef

DEFAULT_KEY = "nfl-sleeper"
"""The competition a script runs over when none is named: the only one that simulates its matchups."""


def chosen(argv: list[str]) -> str:
    """The competition a command line names after the script, or the default."""
    return argv[1] if len(argv) > 1 else DEFAULT_KEY


def first_league(provider: CompetitionProvider, label: str) -> LeagueRef:
    """The first league the account plays in for this competition.

    Raises:
        LeagueNotFoundError: it plays in none this season — an answer, but nothing to run over.
    """
    refs = provider.list_leagues()
    if not refs:
        raise LeagueNotFoundError(f"this account has no {label} league this season.")
    return refs[0]


def open_league[P](registry: Registry, key: str, port: type[P], what: str) -> tuple[CompetitionEntry, P, LeagueRef]:
    """The competition `key` names, as the port a script needs, and the league it runs over.

    Raises:
        FrontOfficeError: no such competition, it is not configured, cannot do `what`, or has no league.
    """
    entry = registry.find(key)
    competition = entry.open()
    provider = entry.as_port(competition, port, what)
    return entry, provider, first_league(competition, entry.label)
