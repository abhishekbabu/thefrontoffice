"""Players: your roster, one player's drawer, a comparison, and a search by name."""

from typing import Annotated

from fastapi import APIRouter, Query

from thefrontoffice.adapters.inbound.web.routes.deps import Capability, CurrentWiring, Provider
from thefrontoffice.application import comparing
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import (
    MAX_COMPARED,
    PlayerCard,
    PlayerComparison,
    PlayerDetail,
    PlayerOrder,
    PlayerRef,
)
from thefrontoffice.domain.ports import PlayerSearchProvider, PlayerTabProvider

router = APIRouter()


@router.get("/api/{competition}/leagues/{league_id}/roster", response_model=list[PlayerCard])
def roster(
    competition: str, league_id: str, order: Annotated[PlayerOrder, Query()], provider: Provider
) -> list[PlayerCard]:
    """One card per player, with per-competition columns rendered generically, in the order asked.

    The columns are the competition's own vocabulary — FPL sends Price and xGI,
    football sends Depth — so the client reads whatever keys arrive rather
    than being taught each competition. Ordered here, by the rule a page of
    the wire is, so a column sorts alike on every table.
    """
    return order.ordered(provider.roster(league_id))


@router.get("/api/{competition}/leagues/{league_id}/players/{player_id}", response_model=PlayerDetail)
def player(competition: str, league_id: str, player_id: str, provider: Provider) -> PlayerDetail:
    """Everything worth knowing about one player, when someone asks."""
    return provider.player(league_id, player_id)


@router.get("/api/{competition}/leagues/{league_id}/players/{player_id}/tabs/{tab}", response_model=PlayerDetail)
def player_tab(
    competition: str,
    league_id: str,
    player_id: str,
    tab: str,
    provider: Annotated[PlayerTabProvider, Capability(PlayerTabProvider)],
) -> PlayerDetail:
    """One tab of a player's drawer that is read only when opened (`PlayerDetail.deferred`)."""
    return provider.player_tab(league_id, player_id, tab)


@router.get("/api/{competition}/leagues/{league_id}/compare", response_model=PlayerComparison)
def compare(
    competition: str, league_id: str, ids: Annotated[list[str], Query()], wiring: CurrentWiring
) -> PlayerComparison:
    """Up to four players side by side, from what each one's drawer shows."""
    # Counted before the competition is opened, so a request asking too much is refused as such.
    if not 1 <= len(ids) <= MAX_COMPARED:
        raise InvalidRequestError([f"Compare 1 to {MAX_COMPARED} players."])
    provider = wiring.registry.find(competition).open()
    return comparing.comparison([provider.player(league_id, player_id) for player_id in ids])


@router.get("/api/{competition}/leagues/{league_id}/players", response_model=list[PlayerRef])
def search_players(
    competition: str,
    league_id: str,
    provider: Annotated[PlayerSearchProvider, Capability(PlayerSearchProvider)],
    search: str = "",
) -> list[PlayerRef]:
    """Players whose name holds `search`, rostered or not, for a comparison to add."""
    return provider.search_players(league_id, search)
