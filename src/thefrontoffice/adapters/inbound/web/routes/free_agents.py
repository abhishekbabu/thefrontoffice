"""The free agents: who is still out there, a page at a time."""

from typing import Annotated

from fastapi import APIRouter, Query

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.web.routes.deps import CurrentWiring, Entry, Provider
from thefrontoffice.domain.models import PlayerPage, PlayerQuery

router = APIRouter()


@router.get("/api/{competition}/leagues/{league_id}/free-agents", response_model=PlayerPage)
def free_agents(
    competition: str,
    league_id: str,
    query: Annotated[PlayerQuery, Query()],
    wiring: CurrentWiring,
    entry: Entry,
    provider: Provider,
) -> PlayerPage:
    """One page of who is still out there, best first.

    Ordering happens here rather than in the client because a football pool
    is four thousand players: a client holding fifty of them can only
    reorder those fifty, which is a worse answer than none.
    """
    return presenting.wire(wiring.week(entry, provider), league_id, query)
