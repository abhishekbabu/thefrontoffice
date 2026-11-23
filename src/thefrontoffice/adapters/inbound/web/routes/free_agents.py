"""The free agents: who is still out there, a page at a time, and the model's call on each."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, CurrentWiring, Entry, Provider
from thefrontoffice.application.wire import MAX_JUDGED, MAX_SHOWN
from thefrontoffice.domain.models import PlayerCall, PlayerPage, PlayerQuery
from thefrontoffice.domain.ports import WireProvider

router = APIRouter(prefix=LEAGUE)


class JudgeRequest(BaseModel):
    """The free agents on screen to judge, best first."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_JUDGED)


@router.get("/free-agents", response_model=PlayerPage)
def free_agents(
    key: str,
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


@router.get("/free-agents/calls", response_model=list[PlayerCall])
def kept_calls(
    key: str,
    league_id: str,
    ids: Annotated[list[str], Query(min_length=1, max_length=MAX_SHOWN)],
    wiring: CurrentWiring,
    entry: Entry,
    provider: Annotated[WireProvider, Capability(WireProvider)],
) -> list[PlayerCall]:
    """The kept call on each free agent on screen, without asking the model anything.

    What lets the wire show its calls on load. A player whose situation
    has moved since his call comes back marked stale.
    """
    return wiring.wire(entry, provider).kept(league_id, ids)


@router.post("/free-agents/calls", response_model=list[PlayerCall])
def judge_free_agents(key: str, league_id: str, request: JudgeRequest, wiring: CurrentWiring) -> list[PlayerCall]:
    """A call on each of the free agents on screen, to show on their rows."""
    # Found here rather than by `Capability`: a dependency runs before the body is read, and a malformed one is a 422.
    entry = wiring.registry.by_key(key)
    return wiring.wire(entry, entry.open_as(WireProvider)).judge(league_id, request.player_ids)
