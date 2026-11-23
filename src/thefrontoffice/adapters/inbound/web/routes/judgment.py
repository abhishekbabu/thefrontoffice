"""Everything that asks the model: the week's judgment, calls on free agents, and opening the assistant."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.conversation import Conversation
from thefrontoffice.adapters.inbound.web.routes.deps import CurrentWiring, Entry, OpenChats, Provider
from thefrontoffice.application.wire import MAX_JUDGED, MAX_SHOWN
from thefrontoffice.domain.models import Judgment, PlayerCall, ScoutReport
from thefrontoffice.domain.ports import WireProvider

router = APIRouter()


class JudgeRequest(BaseModel):
    """The free agents on screen to judge, best first."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_JUDGED)


class CallsRequest(BaseModel):
    """The free agents on screen, whose kept calls to show."""

    player_ids: list[str] = Field(min_length=1, max_length=MAX_SHOWN)


class Thread(BaseModel):
    """A conversation opened on the server; asked through the chat endpoint."""

    chat_id: str


@router.post("/api/{competition}/leagues/{league_id}/scout", response_model=ScoutReport)
def scout(competition: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider) -> ScoutReport:
    """Judge the week's to-do list — or return the kept judgment where nothing has changed."""
    return wiring.scout(entry, provider).report(league_id)


@router.get("/api/{competition}/leagues/{league_id}/judgment", response_model=Judgment | None)
def judgment(
    competition: str, league_id: str, wiring: CurrentWiring, entry: Entry, provider: Provider
) -> Judgment | None:
    """The league's last judgment, or null — read without asking the model anything.

    What lets the week show its verdicts on load: judging is a click,
    and a reload should not throw the answer away.
    """
    return wiring.scout(entry, provider).latest(league_id)


@router.post("/api/{competition}/leagues/{league_id}/assistant", response_model=Thread)
def assistant(
    competition: str, league_id: str, wiring: CurrentWiring, chats: OpenChats, entry: Entry, provider: Provider
) -> Thread:
    """Open the conversation that follows you around this league.

    Briefed on nothing yet: each question says what is on screen, and is
    briefed on whatever of that it has not seen. The turns then go through
    the chat endpoint like any other conversation.
    """
    opened = wiring.ask(entry, provider).assistant(league_id)
    return Thread(chat_id=chats.remember(Conversation(opened)))


@router.post("/api/{competition}/leagues/{league_id}/free-agents/judge", response_model=list[PlayerCall])
def judge_free_agents(
    competition: str,
    league_id: str,
    request: JudgeRequest,
    wiring: CurrentWiring,
) -> list[PlayerCall]:
    """A call on each of the free agents on screen, to show on their rows."""
    entry = wiring.registry.find(competition)
    return wiring.wire(entry, entry.open_as(WireProvider)).judge(league_id, request.player_ids)


@router.post("/api/{competition}/leagues/{league_id}/free-agents/calls", response_model=list[PlayerCall])
def free_agent_calls(
    competition: str,
    league_id: str,
    request: CallsRequest,
    wiring: CurrentWiring,
) -> list[PlayerCall]:
    """The kept call on each free agent on screen, without asking the model anything.

    What lets the wire show its calls on load. A player whose situation
    has moved since his call comes back marked stale.
    """
    entry = wiring.registry.find(competition)
    return wiring.wire(entry, entry.open_as(WireProvider)).kept(league_id, request.player_ids)
