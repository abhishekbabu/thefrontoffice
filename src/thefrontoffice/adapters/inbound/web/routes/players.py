"""Players: your roster, one player's drawer, a comparison, a search by name, and who is untouchable."""

from typing import Annotated

from fastapi import APIRouter, Query

from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, CurrentWiring, Entry, Provider
from thefrontoffice.application import comparing
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import (
    MAX_COMPARED,
    PlayerCard,
    PlayerComparison,
    PlayerDetail,
    PlayerOrder,
    PlayerRef,
    UntouchableMark,
    Untouchables,
)
from thefrontoffice.domain.ports import PlayerSearchProvider, PlayerTabProvider

router = APIRouter(prefix=LEAGUE)


@router.get("/roster", response_model=list[PlayerCard])
def roster(key: str, league_id: str, order: Annotated[PlayerOrder, Query()], provider: Provider) -> list[PlayerCard]:
    """One card per player, with per-competition columns rendered generically, in the order asked.

    The columns are the competition's own vocabulary — FPL sends Price and xGI,
    football sends Depth — so the client reads whatever keys arrive rather
    than being taught each competition. Ordered here, by the rule a page of
    the wire is, so a column sorts alike on every table.
    """
    return order.ordered(provider.roster(league_id))


@router.get("/players/{player_id}", response_model=PlayerDetail)
def player(key: str, league_id: str, player_id: str, provider: Provider) -> PlayerDetail:
    """Everything worth knowing about one player, when someone asks."""
    return provider.player(league_id, player_id)


@router.get("/players/{player_id}/tabs/{tab}", response_model=PlayerDetail)
def player_tab(
    key: str,
    league_id: str,
    player_id: str,
    tab: str,
    provider: Annotated[PlayerTabProvider, Capability(PlayerTabProvider)],
) -> PlayerDetail:
    """One tab of a player's drawer that is read only when opened (`PlayerDetail.deferred`)."""
    return provider.player_tab(league_id, player_id, tab)


@router.get("/compare", response_model=PlayerComparison)
def compare(key: str, league_id: str, ids: Annotated[list[str], Query()], wiring: CurrentWiring) -> PlayerComparison:
    """Up to four players side by side, from what each one's drawer shows."""
    # Counted before the competition is opened, so a request asking too much is refused as such.
    if not 1 <= len(ids) <= MAX_COMPARED:
        raise InvalidRequestError([f"Compare 1 to {MAX_COMPARED} players."])
    provider = wiring.registry.by_key(key).open()
    return comparing.comparison([provider.player(league_id, player_id) for player_id in ids])


@router.get("/players", response_model=list[PlayerRef])
def search_players(
    key: str,
    league_id: str,
    provider: Annotated[PlayerSearchProvider, Capability(PlayerSearchProvider)],
    search: str = "",
) -> list[PlayerRef]:
    """Players whose name holds `search`, rostered or not, for a comparison to add."""
    return provider.search_players(league_id, search)


@router.get("/untouchables", response_model=Untouchables)
def untouchables(key: str, league_id: str, wiring: CurrentWiring, entry: Entry) -> Untouchables:
    """The players on your roster you marked untouchable: never a drop, a trade away or a sale."""
    return wiring.untouchable(entry).listed(league_id)


@router.post("/untouchables", response_model=Untouchables)
def mark_untouchable(key: str, league_id: str, mark: UntouchableMark, wiring: CurrentWiring) -> Untouchables:
    """Mark one player untouchable, or clear his mark; every untouchable in the league after it."""
    # Found here rather than by `Entry`: a dependency runs before the body is read, and a malformed one is a 422.
    return wiring.untouchable(wiring.registry.by_key(key)).mark(league_id, mark)
