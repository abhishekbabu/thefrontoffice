"""What the web adapter reads off the registry, free of any web framework.

The routes call these, and so can a test with no server running. Building a
provider is the side-effecting part — it can open an OAuth flow — so the
registry entry does it only once a competition has actually been chosen.
"""

from pydantic import BaseModel

from thefrontoffice.adapters.inbound.remedies import Remedy, remedy
from thefrontoffice.bootstrap import CompetitionEntry
from thefrontoffice.domain.errors import ErrorCode, FrontOfficeError, NotConfiguredError


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

    plans_ahead: bool
    """Whether its weeks ahead and trades worth offering can be shown."""

    configured: bool
    """Whether the credentials this competition needs are set."""

    requires: str

    ready: bool
    """Whether it can actually be used. Configured is necessary, not sufficient."""

    blocked_reason: str = ""
    blocked_code: ErrorCode | None = None
    blocked_remedy: Remedy | None = None
    """What stands in the way, and what the client can offer to do about it."""


def competition(entry: CompetitionEntry) -> Competition:
    """An entry as the picker sees it, including why it cannot be opened.

    Offering something that will only fail on the next click is worse than
    greying it out and saying what is missing. An unconfigured entry is never
    probed: its readiness check may look for a token it has no reason to have.
    """
    configured = entry.is_configured()
    blocked: FrontOfficeError | None = None if configured else NotConfiguredError(entry.label, entry.requires)
    if configured:
        try:
            entry.check_ready()
        except FrontOfficeError as e:
            blocked = e
    return Competition(
        key=entry.key,
        sport=entry.sport,
        competition=entry.competition,
        platform=entry.platform,
        label=entry.label,
        name=entry.name,
        judges_wire=entry.judges_wire,
        plans_ahead=entry.plans_ahead,
        configured=configured,
        requires=entry.requires,
        ready=blocked is None,
        blocked_reason=str(blocked or ""),
        blocked_code=blocked.code if blocked else None,
        blocked_remedy=remedy(blocked.code) if blocked else None,
    )
