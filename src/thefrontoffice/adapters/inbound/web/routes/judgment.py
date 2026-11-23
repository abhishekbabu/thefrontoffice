"""The week's judgment: the model's verdict on the to-do list, made or kept."""

from fastapi import APIRouter

from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, CurrentWiring, Entry, Provider
from thefrontoffice.domain.models import Judgment, ScoutReport

router = APIRouter(prefix=LEAGUE)


@router.post("/judgment", response_model=ScoutReport)
def judge(key: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider) -> ScoutReport:
    """Judge the week's to-do list — or return the kept judgment where nothing has changed."""
    return wiring.scout(entry, provider).report(league_id)


@router.get("/judgment", response_model=Judgment | None)
def judgment(key: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider) -> Judgment | None:
    """The league's last judgment, or null — read without asking the model anything.

    What lets the week show its verdicts on load: judging is a click,
    and a reload should not throw the answer away.
    """
    return wiring.scout(entry, provider).latest(league_id)
