"""Gemini's implementation of the AnalysisModel port."""

import logging
import time
from collections.abc import Callable
from typing import Protocol

from google import genai
from google.genai import errors, types
from google.genai.chats import Chat
from pydantic import ValidationError

from thefrontoffice.domain.errors import (
    AIKeyInvalidError,
    AIQuotaError,
    AIResponseError,
    AIUnavailableError,
    FrontOfficeError,
)
from thefrontoffice.domain.ports import AnalysisModel, ChatReply, ChatSession, HistoryTurn, TModel

from .constants import MODEL_FLASH, MODEL_PRO

logger = logging.getLogger(__name__)

NAME = "Gemini"
KEY_SETTING = "GOOGLE_API_KEY"


def translate(error: Exception) -> FrontOfficeError:
    """Turn a vendor failure into one of the three things worth telling apart.

    The SDK's message embeds a repr of a Google RPC payload — nested dicts,
    type URLs, a locale — which is unreadable anywhere a person is looking. A
    rejected key is something to go and fix; a spent quota is something
    another provider can absorb; anything else is a failed answer.
    """
    if isinstance(error, errors.APIError):
        if error.code in (401, 403) or "API key not valid" in (error.message or ""):
            return AIKeyInvalidError(NAME, KEY_SETTING)
        if error.code == 429 or error.status == "RESOURCE_EXHAUSTED":
            return AIQuotaError(NAME)
    return AIResponseError()


def _translated[T](what: str, call: Callable[[], T]) -> T:
    """`call`, with any failure logged and raised as a domain error.

    Broad on purpose, and only here: the SDK raises its own `APIError` for an
    answer it refused, but its transport's exceptions unwrapped for a dropped
    connection — and either way the next provider should get the turn.
    """
    try:
        return call()
    except Exception as e:
        logger.error(f"Gemini {what} failed: {e}")
        raise translate(e) from e


class GeminiChat:
    """A genai chat whose failures arrive as domain errors.

    The SDK's chat raises its own exceptions, so a caller could not tell a
    spent quota — which another provider can absorb — from anything else.
    """

    def __init__(self, chat: Chat) -> None:
        self._chat = chat

    def send_message(self, message: str) -> ChatReply:
        return _translated("chat", lambda: self._chat.send_message(message))


class GenAIModels(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: types.ContentListUnionDict,
        config: types.GenerateContentConfigOrDict | None = None,
    ) -> types.GenerateContentResponse: ...


class GenAIChats(Protocol):
    def create(
        self,
        *,
        model: str,
        config: types.GenerateContentConfigOrDict | None = None,
        history: list[types.ContentOrDict] | None = None,
    ) -> Chat: ...


class GenAISource(Protocol):
    """What the adapter reads the genai SDK through: one call to generate, one to open a chat.

    `genai.Client` satisfies it, and so does a test's fake, which is then
    checked against these signatures rather than slipped in as a stand-in.
    """

    @property
    def models(self) -> GenAIModels: ...

    @property
    def chats(self) -> GenAIChats: ...


def connect(api_key: str | None) -> GenAISource | None:
    """The SDK client for `api_key`; None without one, which leaves the model unavailable."""
    if not api_key:
        logger.info(f"No {KEY_SETTING}; Gemini is unavailable.")
        return None
    return genai.Client(api_key=api_key)


class GeminiClient(AnalysisModel):
    """Gemini's implementation of the AnalysisModel port: Pro analyses, Flash parses.

    Inherits the protocol explicitly rather than matching it structurally, so
    the type checker fails here — at the adapter — if the two ever drift apart,
    instead of at whichever caller happens to notice first.
    """

    name = NAME
    key_setting = KEY_SETTING

    def __init__(self, *, client: GenAISource | None) -> None:
        """`client` is None where no key is set; `connect` builds one from a key."""
        self.client = client

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        """An analysis of `prompt` by Pro, held to `schema` by the API itself.

        A response schema cannot be combined with the Google Search tool; see
        `structure_text` for the path that needs both.

        Raises:
            AIUnavailableError: no credentials.
            AIKeyInvalidError, AIQuotaError, AIResponseError: as `translate` sorts them.
        """
        return self._generate(MODEL_PRO, prompt, schema)

    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        """`text` put into `schema` by Flash: parsing is the cheap model's job."""
        return self._generate(MODEL_FLASH, f"{instruction}\n\n{text}", schema)

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        """Start a chat session with the model, its failures translated like every other call's."""
        client = self._require_client()
        config = None
        if enable_search:
            search_tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(tools=[search_tool])

        # Built as the SDK's own type rather than handed our dicts to coerce:
        # the shape is ours, and a change to theirs then fails here by name.
        history: list[types.ContentOrDict] = [
            types.Content(role=turn["role"], parts=[types.Part(text=part) for part in turn["parts"]])
            for turn in initial_history or []
        ]
        return GeminiChat(client.chats.create(model=MODEL_PRO, history=history, config=config))

    def _require_client(self) -> GenAISource:
        if self.client is None:
            raise AIUnavailableError(keys=[KEY_SETTING])
        return self.client

    def _generate(self, model: str, prompt: str, schema: type[TModel]) -> TModel:
        client = self._require_client()
        started = time.perf_counter()
        response = _translated(
            f"{model} call",
            lambda: client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            ),
        )
        _log_usage(model, response, time.perf_counter() - started)
        return _parsed(response, schema)


def _parsed(response: types.GenerateContentResponse, schema: type[TModel]) -> TModel:
    """The validated answer off a genai response, or raise."""
    if isinstance(response.parsed, schema):
        return response.parsed

    # genai populates .parsed for schema responses; validating the raw JSON
    # ourselves means a client-library change degrades to that rather than a crash.
    if not response.text:
        raise AIResponseError("The model returned nothing usable. Try again.")
    try:
        return schema.model_validate_json(response.text)
    except ValidationError as e:
        logger.error(f"Response did not match {schema.__name__}: {e}")
        raise AIResponseError("The model's answer did not fit the expected shape. Try again.") from e


def _log_usage(model: str, response: types.GenerateContentResponse, elapsed: float) -> None:
    """Record what a call cost.

    Gemini Pro on a large prompt is the only real expense here, and nothing
    else measures it — without this there is no way to answer "what does a
    scout report cost?" from production logs.
    """
    usage = response.usage_metadata
    if usage is None:
        logger.info(f"{model} responded in {elapsed:.2f}s (no usage metadata)")
        return
    cached = usage.cached_content_token_count
    logger.info(
        f"{model} responded in {elapsed:.2f}s — {usage.prompt_token_count} in, "
        f"{usage.candidates_token_count} out, {usage.total_token_count} total"
        + (f", {cached} cached" if cached else "")
    )
