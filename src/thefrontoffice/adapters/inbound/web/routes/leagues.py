"""The leagues this account plays in, per competition."""

from fastapi import APIRouter

from thefrontoffice.adapters.inbound.web.routes.deps import Provider
from thefrontoffice.domain.ports import LeagueRef

router = APIRouter()


@router.get("/api/{competition}/leagues", response_model=list[LeagueRef])
def list_leagues(competition: str, provider: Provider) -> list[LeagueRef]:
    return provider.list_leagues()
