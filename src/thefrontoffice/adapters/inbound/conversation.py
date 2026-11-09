"""A conversation as both inbound adapters hold it: the open chat, and what has been said in it.

The web page and the terminal ask follow-ups the same way, so they fail the
same way: a vendor fault the adapters did not translate becomes one
`AIResponseError` here, logged, rather than a 502 in one place and a printed
line in the other.
"""

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from thefrontoffice.application.asking import Assistant
from thefrontoffice.domain.errors import AIResponseError, FrontOfficeError
from thefrontoffice.domain.models import Subject
from thefrontoffice.domain.ports import ChatReply, ChatSession

logger = logging.getLogger(__name__)

NO_ANSWER = "The model did not answer. Try asking again."


class Turn(BaseModel):
    """One thing said: by the person, or by the model."""

    role: Literal["you", "model"]
    text: str


class Conversation:
    """An open chat, and its turns so far — the record a page reopened later reads back.

    The chat is a plain one — a report's follow-ups in the terminal — or the
    assistant, which is also told what is on screen with each question.
    """

    def __init__(self, chat: ChatSession | Assistant) -> None:
        self._chat = chat
        self.turns: list[Turn] = []
        """Each question and its answer, oldest first. A question that got no answer is not kept:
        the model never took it into the conversation either."""

    def ask(self, message: str, on_screen: Sequence[Subject] = ()) -> str:
        """The model's answer to `message`, asked with `on_screen` in view, kept with it.

        Only the question is kept as its turn, not the briefing that rode with it.

        Raises:
            FrontOfficeError: the model failed — a vendor fault arrives as `AIResponseError`.
        """
        try:
            answer = self._send(message, on_screen).text
        except FrontOfficeError:
            raise
        except Exception as e:  # anything the adapters did not translate
            # Its message is a repr of a vendor's RPC payload: the log is where that belongs.
            logger.error(f"Follow-up failed: {e}")
            raise AIResponseError(NO_ANSWER) from e
        self.turns += [Turn(role="you", text=message), Turn(role="model", text=answer)]
        return answer

    def _send(self, message: str, on_screen: Sequence[Subject]) -> ChatReply:
        if isinstance(self._chat, Assistant):
            return self._chat.ask(message, on_screen)
        return self._chat.send_message(message)
