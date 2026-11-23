"""The season: the league beyond this week, and your weeks ahead."""

from typing import Annotated

from fastapi import APIRouter

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, CurrentWiring, Entry, Provider
from thefrontoffice.domain.models import LeagueSchedule, Outlook
from thefrontoffice.domain.ports import OutlookProvider

router = APIRouter(prefix=LEAGUE)


@router.get("/season", response_model=LeagueSchedule)
def season(key: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider) -> LeagueSchedule:
    """The league beyond this week: the season, the table, the real games.

    Separate from `/week` because it answers a different question and
    costs requests the week does not need — nobody checking their lineup
    should wait on the whole season's fixtures.
    """
    return presenting.season(wiring.week(entry, provider).season(league_id))


@router.get("/outlook", response_model=Outlook)
def outlook(key: str, league_id: str, provider: Annotated[OutlookProvider, Capability(OutlookProvider)]) -> Outlook:
    """Your next few weeks as your roster stands, and a pickup for any that comes up short.

    Offered only where a competition can project them, as trades are, so
    one that cannot refuses rather than answering with no weeks.
    """
    return provider.weeks_ahead(league_id)
