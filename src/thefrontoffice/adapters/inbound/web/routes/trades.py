"""The trades worth offering."""

from typing import Annotated

from fastapi import APIRouter

from thefrontoffice.adapters.inbound.web.routes.deps import Capability, CurrentWiring
from thefrontoffice.domain.models import Trades
from thefrontoffice.domain.ports import TradeMarketProvider

router = APIRouter()


@router.get("/api/{competition}/leagues/{league_id}/trades", response_model=Trades)
def trades(
    competition: str,
    league_id: str,
    wiring: CurrentWiring,
    provider: Annotated[TradeMarketProvider, Capability(TradeMarketProvider)],
) -> Trades:
    """The trades that would most raise your playoff chance and that the other side gains from too.

    Its own route because it plays the season out once per trade tried —
    seconds, not the instant a table should take to appear.
    """
    return wiring.market(provider).trades(league_id)
