"""A conversation as both inbound adapters hold it: the open chat, and what has been said in it.

The web page and the terminal ask follow-ups the same way, so they fail the
same way: a vendor fault the adapters did not translate becomes one
`AIResponseError` here, logged, rather than a 502 in one place and a printed
line in the other.
"""

import logging
from typing import Literal

from pydantic import BaseModel

from thefrontoffice.domain.errors import AIResponseError, FrontOfficeError
from thefrontoffice.domain.ports import ChatSession

logger = logging.getLogger(__name__)

NO_ANSWER = "The model did not answer. Try asking again."


class Turn(BaseModel):
    """One thing said: by the person, or by the model."""

    role: Literal["you", "model"]
    text: str


class Conversation:
    """An open chat, and its turns so far — the record a page reopened later reads back."""

    def __init__(self, chat: ChatSession) -> None:
        self._chat = chat
        self.turns: list[Turn] = []
        """Each question and its answer, oldest first. A question that got no answer is not kept:
        the model never took it into the conversation either."""

    def ask(self, message: str) -> str:
        """The model's answer to `message`, kept with it.

        Raises:
            FrontOfficeError: the model failed — a vendor fault arrives as `AIResponseError`.
        """
        try:
            answer = self._chat.send_message(message).text
        except FrontOfficeError:
            raise
        except Exception as e:  # anything the adapters did not translate
            # Its message is a repr of a vendor's RPC payload: the log is where that belongs.
            logger.error(f"Follow-up failed: {e}")
            raise AIResponseError(NO_ANSWER) from e
        self.turns += [Turn(role="you", text=message), Turn(role="model", text=answer)]
        return answer
