"""Everyone else in the league: their rosters, and their weeks ahead."""

from typing import Annotated

from fastapi import APIRouter, Query

from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, Provider
from thefrontoffice.domain.models import Outlook, PlayerCard, PlayerOrder, TeamRef
from thefrontoffice.domain.ports import OutlookProvider

router = APIRouter(prefix=LEAGUE)


@router.get("/teams", response_model=list[TeamRef])
def teams(key: str, league_id: str, provider: Provider) -> list[TeamRef]:
    """Everyone in the league, so their rosters can be opened."""
    return provider.teams(league_id)


@router.get("/teams/{team_id}/roster", response_model=list[PlayerCard])
def team_roster(
    key: str, league_id: str, team_id: str, order: Annotated[PlayerOrder, Query()], provider: Provider
) -> list[PlayerCard]:
    """Somebody else's squad, in the same columns as your own, ordered as yours is."""
    return order.ordered(provider.roster_of(league_id, team_id))


@router.get("/teams/{team_id}/outlook", response_model=Outlook)
def team_outlook(
    key: str, league_id: str, team_id: str, provider: Annotated[OutlookProvider, Capability(OutlookProvider)]
) -> Outlook:
    """Somebody else's next few weeks as their roster stands, as `/outlook` reads your own."""
    return provider.weeks_ahead(league_id, team_id)
