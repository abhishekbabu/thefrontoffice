"""Conversations: opened in a league, then read back and asked by id."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.conversation import Conversation, Turn
from thefrontoffice.adapters.inbound.web.routes.deps import LEAGUE, CurrentWiring, Entry, OpenChats, Provider
from thefrontoffice.domain.models import Subject

router = APIRouter()


class Thread(BaseModel):
    """A conversation opened on the server; asked through its turns."""

    chat_id: str


class ChatRequest(BaseModel):
    """A question, and what was on screen when it was asked."""

    message: str = Field(min_length=1)
    on_screen: list[Subject] = Field(default_factory=list, max_length=8)


@router.post(f"{LEAGUE}/chats", response_model=Thread)
def open_chat(
    key: str, league_id: str, wiring: CurrentWiring, chats: OpenChats, entry: Entry, provider: Provider
) -> Thread:
    """Open the conversation that follows you around this league.

    Briefed on nothing yet: each question says what is on screen, and is
    briefed on whatever of that it has not seen. Its turns are then read and
    asked by its id, like any other conversation.
    """
    opened = wiring.ask(entry, provider).assistant(league_id)
    return Thread(chat_id=chats.remember(Conversation(opened)))


@router.get("/api/chats/{chat_id}", response_model=list[Turn])
def turns(chat_id: str, chats: OpenChats) -> list[Turn]:
    """What has been said in a conversation so far — what a page reopened on it shows.

    An id this process does not hold is `chat_expired`, the client's cue to open another.
    """
    return chats.get(chat_id).turns


@router.post("/api/chats/{chat_id}/turns", response_model=list[Turn])
def ask(chat_id: str, request: ChatRequest, chats: OpenChats) -> list[Turn]:
    """Ask the next question in an open conversation; every turn so far, the answer last.

    The whole conversation rather than the answer alone, so the client shows
    what the server holds instead of keeping a copy of its own in step.
    """
    conversation = chats.get(chat_id)
    conversation.ask(request.message, request.on_screen)
    return conversation.turns
