"""The league a script runs over, chosen the same way by each."""

from thefrontoffice.domain.errors import LeagueNotFoundError
from thefrontoffice.domain.ports import CompetitionProvider, LeagueRef


def first_league(provider: CompetitionProvider, label: str) -> LeagueRef:
    """The first league the account plays in for this competition.

    Raises:
        LeagueNotFoundError: it plays in none this season — an answer, but nothing to run over.
    """
    refs = provider.list_leagues()
    if not refs:
        raise LeagueNotFoundError(f"this account has no {label} league this season.")
    return refs[0]
