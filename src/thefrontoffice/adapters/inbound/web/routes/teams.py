"""Everyone else in the league, and their rosters."""

from typing import Annotated

from fastapi import APIRouter, Query

from thefrontoffice.adapters.inbound.web.routes.deps import Provider
from thefrontoffice.domain.models import PlayerCard, PlayerOrder, TeamRef

router = APIRouter()


@router.get("/api/{competition}/leagues/{league_id}/teams", response_model=list[TeamRef])
def teams(competition: str, league_id: str, provider: Provider) -> list[TeamRef]:
    """Everyone in the league, so their rosters can be opened."""
    return provider.teams(league_id)


@router.get("/api/{competition}/leagues/{league_id}/teams/{team_id}/roster", response_model=list[PlayerCard])
def team_roster(
    competition: str, league_id: str, team_id: str, order: Annotated[PlayerOrder, Query()], provider: Provider
) -> list[PlayerCard]:
    """Somebody else's squad, in the same columns as your own, ordered as yours is."""
    return order.ordered(provider.roster_of(league_id, team_id))
