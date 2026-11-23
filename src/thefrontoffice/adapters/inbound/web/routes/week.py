"""The week: the one being played, any other, its real games, and decisions on its to-do items."""

from typing import Annotated

from fastapi import APIRouter

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, Capability, CurrentWiring, Entry, Provider
from thefrontoffice.domain.models import ItemDecision, ItemMark, Slate, Summary
from thefrontoffice.domain.ports import WeekBrowsingProvider

router = APIRouter(prefix=LEAGUE)


@router.get("/week", response_model=Summary)
def week(key: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider) -> Summary:
    """Where the team stands this week, before any report is asked for.

    The page would otherwise be blank for as long as a model call takes,
    showing nothing the app already knows. To-do items carry what the
    manager decided about them — dismissed, snoozed, or back since.
    """
    return presenting.week(wiring.week(entry, provider).week(league_id))


@router.get("/weeks/{week}", response_model=Summary)
def week_of(
    key: str,
    league_id: str,
    week: int,
    provider: Annotated[WeekBrowsingProvider, Capability(WeekBrowsingProvider)],
) -> Summary:
    """Another week of the season: one played as it finished, one to come as the rosters project.

    The week being played is `/week`'s, with its to-do list and its
    forecast; this answers the rest, with neither. Offered only where a
    competition can, so one that cannot refuses rather than answering
    with the week being played.
    """
    return provider.week_of(league_id, week)


@router.get("/weeks/{week}/games", response_model=Slate)
def games_of(
    key: str,
    league_id: str,
    week: int,
    provider: Annotated[WeekBrowsingProvider, Capability(WeekBrowsingProvider)],
) -> Slate:
    """The real games of any week of the season, the week being played included, and its byes."""
    return provider.games_of(league_id, week)


@router.post("/items", response_model=ItemMark)
def decide(key: str, league_id: str, decision: ItemDecision, wiring: CurrentWiring) -> ItemMark:
    """Dismiss, snooze or restore one to-do item; what the decision makes of it, for its row to show."""
    # Found here rather than by `Entry`: a dependency runs before the body is read, and a malformed one is a 422.
    return wiring.decisions.decide(wiring.registry.by_key(key).key, league_id, decision)
