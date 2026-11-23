"""A conversation already open: what has been said in it, and the next question."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from thefrontoffice.adapters.inbound.conversation import Turn
from thefrontoffice.adapters.inbound.web.routes.deps import OpenChats
from thefrontoffice.domain.models import Subject

router = APIRouter()


class ChatRequest(BaseModel):
    """A question, and what was on screen when it was asked."""

    message: str = Field(min_length=1)
    on_screen: list[Subject] = Field(default_factory=list, max_length=8)


@router.get("/api/chat/{chat_id}", response_model=list[Turn])
def turns(chat_id: str, chats: OpenChats) -> list[Turn]:
    """What has been said in a conversation so far — what a page reopened on it shows.

    An id this process does not hold is `chat_expired`, the client's cue to open another.
    """
    return chats.get(chat_id).turns


@router.post("/api/chat/{chat_id}", response_model=list[Turn])
def ask(chat_id: str, request: ChatRequest, chats: OpenChats) -> list[Turn]:
    """Ask the next question in an open conversation; every turn so far, the answer last.

    The whole conversation rather than the answer alone, so the client shows
    what the server holds instead of keeping a copy of its own in step.
    """
    conversation = chats.get(chat_id)
    conversation.ask(request.message, request.on_screen)
    return conversation.turns
