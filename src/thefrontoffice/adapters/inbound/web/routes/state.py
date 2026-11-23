"""What the app holds between requests: open conversations, and logins in progress.

Built once per app by `create_app` and kept on `app.state`, beside the wiring.
In-process because this serves exactly one person on one machine; a second
worker would need somewhere shared to put these.
"""

import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from thefrontoffice.adapters.inbound.conversation import Conversation
from thefrontoffice.domain.errors import ChatExpiredError, FrontOfficeError
from thefrontoffice.domain.ports import AccountLogin

logger = logging.getLogger(__name__)

MAX_CHATS = 64
"""Conversations held at once. Each carries its whole history, resent to the
model every turn, so one person's week of conversations is bounded here
rather than by how long the process happens to run."""


class Chats:
    """Open conversations, by id, the least recently used dropped past `MAX_CHATS`.

    A chat is a live object holding conversation state, so it cannot cross the
    wire. It stays here, with what has been said in it, and the client refers
    to it by id — and reads its turns back from here, so a page reopened shows
    the conversation the server is still carrying on. One dropped answers as
    one never opened: `chat_expired`, the client's cue to open another.
    """

    def __init__(self, limit: int = MAX_CHATS) -> None:
        self._limit = limit
        self._open: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, conversation: Conversation) -> str:
        chat_id = uuid.uuid4().hex
        with self._lock:
            self._open[chat_id] = conversation
            while len(self._open) > self._limit:
                self._open.popitem(last=False)
        return chat_id

    def get(self, chat_id: str) -> Conversation:
        """Raises:
        ChatExpiredError: this process does not hold it — it restarted since, or dropped it as the oldest.
        """
        with self._lock:
            if chat_id not in self._open:
                raise ChatExpiredError()
            self._open.move_to_end(chat_id)
            return self._open[chat_id]


class LoginState(BaseModel):
    """Where a platform's login handshake has got to."""

    status: Literal["idle", "running", "ok", "failed"]
    detail: str = ""


class Login:
    """One platform's handshake, which opens a browser and waits for a click no request can hold open.

    It runs on a thread, and the client watches `state` instead.
    """

    def __init__(self, platform: str, account: Callable[[], AccountLogin]) -> None:
        self._platform = platform
        self._account = account
        self._lock = threading.Lock()
        self.state = LoginState(status="idle")

    def start(self) -> LoginState:
        with self._lock:
            if self.state.status == "running":
                return self.state
            # A stale outcome from a previous attempt would read as this one's.
            self.state = LoginState(status="running", detail="Authorize in the browser tab that just opened.")
        threading.Thread(target=self._run, daemon=True).start()
        return self.state

    def _run(self) -> None:
        """Authorize, then confirm the grant is real before reporting success."""
        try:
            account = self._account()
            account.login(force=True)
            account.verify()
        except FrontOfficeError as e:
            logger.error(f"{self._platform} authorization failed: {e}")
            self.state = LoginState(status="failed", detail=str(e))
        except Exception as e:  # a browser or socket failure, not a domain condition
            logger.error(f"{self._platform} authorization failed unexpectedly: {e}")
            self.state = LoginState(status="failed", detail=f"Authorization failed: {e}")
        else:
            self.state = LoginState(status="ok", detail="The platform accepted a read with the new grant.")


type Logins = dict[str, Login]
"""Each platform's login, by the platform's name in its entries."""
