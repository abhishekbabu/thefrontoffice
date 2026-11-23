"""What this installation offers: its competitions, and what it can do with them."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.web import data
from thefrontoffice.adapters.inbound.web.routes.deps import CurrentWiring
from thefrontoffice.application.wire import MAX_JUDGED

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
