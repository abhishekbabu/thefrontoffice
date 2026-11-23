"""What this installation offers: its competitions, what it can do with them, and the leagues in each."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, CurrentWiring, Provider
from thefrontoffice.application.wire import MAX_JUDGED
from thefrontoffice.domain.ports import LeagueRef, LeagueRefreshProvider

router = APIRouter()


class Limits(BaseModel):
    """The engines' own bounds, sent so the page can say them rather than restate them."""

    judged: int = Field(description="How many free agents one judging asks about: a screen's worth of the best.")


class Capabilities(BaseModel):
    """What the app can do here, as opposed to what it knows how to do."""

    ai: bool
    """Whether a model can be called. Everything that needs one hides without it."""

    limits: Limits


@router.get("/api/competitions", response_model=list[data.Competition])
def list_sports(wiring: CurrentWiring) -> list[data.Competition]:
    """Every competition, including ones this machine has no credentials for.

    Unconfigured ones are returned rather than hidden so the UI can say
    what to set instead of silently offering less than it could.
    """
    return [data.competition(entry) for entry in wiring.registry.entries]


@router.get("/api/capabilities", response_model=Capabilities)
def capabilities(wiring: CurrentWiring) -> Capabilities:
    """What this installation can actually do.

    Read before anything is offered. Without a key there is no analysis to
    give, so nothing that needs one is shown — rather than shown and then
    refused, which is a click spent learning the app cannot do it.
    """
    return Capabilities(ai=wiring.ai_available(), limits=Limits(judged=MAX_JUDGED))


@router.get("/api/competitions/{key}/leagues", response_model=list[LeagueRef])
def list_leagues(key: str, provider: Provider) -> list[LeagueRef]:
    """Every league this account plays in for the competition `key` names: 'nba-yahoo', never a bare 'nba'."""
    return provider.list_leagues()


class Refreshed(BaseModel):
    """What a refresh dropped."""

    dropped: int = Field(description="How many kept platform reads went, to be asked for again on the next page.")


@router.post(f"{LEAGUE}/refresh", response_model=Refreshed)
def refresh(
    key: str,
    league_id: str,
    provider: Annotated[LeagueRefreshProvider, Capability(LeagueRefreshProvider)],
) -> Refreshed:
    """Drop what is kept of one league that a move or a new week changes, so its pages read the platform again.

    Each read is kept as long as its answer usually holds — a Yahoo roster an
    hour — which is too long right after the manager has made a move.
    """
    return Refreshed(dropped=provider.refresh(league_id))
