"""What the web adapter reads off the registry, free of any web framework.

The routes call these, and so can a test with no server running. Nothing here
builds a provider: what an entry can do is read off its provider's class, and
whether it is ready off its settings and a cheap readiness check.
"""

from pydantic import BaseModel

from thefrontoffice.adapters.inbound.remedies import ErrorBody
from thefrontoffice.bootstrap import CompetitionEntry
from thefrontoffice.domain.ports import OutlookProvider, TradeMarketProvider, WireProvider


class Competition(BaseModel):
    """One registry entry as the picker sees it: who it is, what it can do, and whether it can be opened."""

    key: str
    """Identifies this entry in every route and picker: 'nba-yahoo'."""

    sport: str
    """The game itself — basketball, football, soccer — so the client can group
    the competitions that are the same sport under one heading."""

    competition: str
    """Which competition: 'nba', 'nfl', 'premier-league'."""

    platform: str
    label: str
    name: str
    """The competition without its platform, for wherever only one platform carries it."""

    judges_wire: bool
    """Whether its free agents can be judged — offered only where it is."""

    plans_weeks: bool
    """Whether its coming weeks can be projected."""

    finds_trades: bool
    """Whether the trades worth offering can be found."""

    configured: bool
    """Whether the credentials this competition needs are set."""

    requires: str

    blocked: ErrorBody | None = None
    """What stands in the way, as any failure is reported, so the client offers the same remedy.
    None where it can be opened — being configured is necessary, not sufficient."""


def competition(entry: CompetitionEntry) -> Competition:
    """An entry as the picker sees it, including why it cannot be opened.

    Offering something that will only fail on the next click is worse than
    greying it out and saying what is missing.
    """
    blocker = entry.blocker()
    return Competition(
        key=entry.key,
        sport=entry.sport,
        competition=entry.competition,
        platform=entry.platform,
        label=entry.label,
        name=entry.name,
        judges_wire=entry.can(WireProvider),
        plans_weeks=entry.can(OutlookProvider),
        finds_trades=entry.can(TradeMarketProvider),
        configured=entry.is_configured(),
        requires=entry.requires,
        blocked=ErrorBody.of(blocker) if blocker else None,
    )
