"""Gemini's implementation of the AnalysisModel port."""

import logging
import time
from typing import Protocol

from google import genai
from google.genai import types
from google.genai.chats import Chat

from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import (
    AIKeyInvalidError,
    AIQuotaError,
    AIResponseError,
    AIUnavailableError,
    FrontOfficeError,
)
from thefrontoffice.domain.models import TradeProposal
from thefrontoffice.domain.ports import AnalysisModel, ChatReply, ChatSession, HistoryTurn, TModel

from .constants import MODEL_FLASH, MODEL_PRO

logger = logging.getLogger(__name__)


def translate(error: Exception) -> FrontOfficeError:
    """Turn a vendor failure into a sentence.

    The SDK raises with a Python repr of a Google RPC payload embedded in it —
    nested dicts, type URLs, a locale — which is unreadable anywhere a person
    is looking. The two cases worth telling apart are a key that was rejected
    and a quota that ran out, because only the first is something to go and fix.
    """
    text = str(error)
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return AIKeyInvalidError()
    if "RESOURCE_EXHAUSTED" in text or "quota" in text.lower() or "429" in text:
        return AIQuotaError()
    return AIResponseError()


class GeminiChat:
    """A genai chat whose failures arrive as domain errors.

    The SDK's chat raises its own exceptions, so a caller could not tell a
    spent quota — which another provider can absorb — from anything else.
    """

    def __init__(self, chat: Chat) -> None:
        self._chat = chat

    def send_message(self, message: str) -> ChatReply:
        try:
            return self._chat.send_message(message)
        except Exception as e:
            logger.error(f"Gemini chat failed: {e}")
            raise translate(e) from e


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


class GeminiClient(AnalysisModel):
    """Gemini's implementation of the AnalysisModel port.

    Inherits the protocol explicitly rather than matching it structurally, so
    the type checker fails here — at the adapter — if the two ever drift apart,
    instead of at whichever caller happens to notice first.
    """

    @property
    def is_available(self) -> bool:
        """Whether a call can be made at all.

        Read before offering anything that needs the model: an app that shows a
        button and then explains it cannot be pressed has wasted the click.
        """
        return self.client is not None

    def __init__(self, api_key: str | None = None):
        # Read at construction rather than bound as a default, so a key saved in
        # Settings takes effect on the next call instead of the next restart.
        key = api_key if api_key is not None else settings.gemini_api_key
        self.client: GenAISource | None = genai.Client(api_key=key) if key else None
        if not key:
            logger.info("No GOOGLE_API_KEY; the model is unavailable and nothing will offer it.")

    @staticmethod
    def _log_usage(model: str, response: object, elapsed: float) -> None:
        """Record what a call cost.

        Gemini Pro on a large prompt is the only real expense here, and nothing
        else measures it — without this there is no way to answer "what does a
        scout report cost?" from production logs.
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            logger.info(f"{model} responded in {elapsed:.2f}s (no usage metadata)")
            return
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        cached = getattr(usage, "cached_content_token_count", None)
        logger.info(
            f"{model} responded in {elapsed:.2f}s — "
            f"{prompt_tokens} in, {output_tokens} out, {total} total" + (f", {cached} cached" if cached else "")
        )

    # signatures (verified by inspect.signature and isinstance at runtime); pyrefly
    # cannot prove two generic method types equivalent across modules.
    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        """Generate a response conforming to `schema`.

        Uses response-schema mode rather than asking for a format in prose, so a
        model that ignores the shape fails here instead of producing something
        unrenderable.

        A response schema cannot be combined with the Google Search tool; see
        `structure_text` for the path that needs both.

        Raises:
            AIUnavailableError: no credentials.
            AIResponseError: the call failed, or returned nothing parseable.
        """
        if not self.client:
            raise AIUnavailableError()

        try:
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_PRO,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
            self._log_usage(MODEL_PRO, response, time.perf_counter() - started)
        except Exception as e:
            logger.error(f"Structured generation failed: {e}")
            raise translate(e) from e

        return self._parsed_or_raise(response, schema)

    # signatures (verified by inspect.signature and isinstance at runtime); pyrefly
    # cannot prove two generic method types equivalent across modules.
    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        """Convert prose the model already produced into `schema`, using Flash.

        The trade path needs Google Search for live injury and standings data,
        and search cannot be combined with a response schema. Rather than give
        up one or the other, the search-grounded prose is structured in a second,
        cheap pass — the same Flash-for-parsing split parse_trade_string uses.
        """
        if not self.client:
            raise AIUnavailableError()

        prompt = (
            f"{instruction}\n\nConvert the following analysis verbatim — do not add, drop or soften anything:\n\n{text}"
        )
        try:
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_FLASH,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
            self._log_usage(MODEL_FLASH, response, time.perf_counter() - started)
        except Exception as e:
            logger.error(f"Structuring failed: {e}")
            raise translate(e) from e

        return self._parsed_or_raise(response, schema)

    @staticmethod
    def _parsed_or_raise(response: object, schema: type[TModel]) -> TModel:
        """Pull the validated model off a genai response, or raise."""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        # genai populates .parsed for schema responses; fall back to the raw
        # JSON so a client-library change degrades to a parse rather than a crash.
        raw = getattr(response, "text", None)
        if raw:
            try:
                return schema.model_validate_json(raw)
            except Exception as e:
                logger.error(f"Response did not match {schema.__name__}: {e}")
                raise AIResponseError("The model's answer did not fit the expected shape. Try again.") from e
        raise AIResponseError("The model returned nothing usable. Try again.")

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        """Start a chat session with the model, its failures translated like every other call's."""
        if not self.client:
            raise AIUnavailableError()

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
        return GeminiChat(self.client.chats.create(model=MODEL_PRO, history=history, config=config))

    def parse_trade_string(self, text: str) -> TradeProposal:
        """
        Parse a natural language trade string into a structured TradeProposal.
        Uses Gemini Flash for speed and cost efficiency.
        """

        if not self.client:
            raise AIUnavailableError()

        prompt = f"""
        Extract the players being given and received in this trade offer.
        Return ONLY a JSON object with keys "giving" and "receiving".
        Using full player names.

        Trade: "{text}"
        """

        try:
            started = time.perf_counter()
            response = self.client.models.generate_content(
                model=MODEL_FLASH, contents=prompt, config={"response_mime_type": "application/json"}
            )
            self._log_usage(MODEL_FLASH, response, time.perf_counter() - started)

            import json

            text = response.text or "{}"
            data = json.loads(text)
            # The model returns a bare string when only one player is involved.
            giving = data.get("giving", [])
            receiving = data.get("receiving", [])

            if isinstance(giving, str):
                giving = [giving]
            if isinstance(receiving, str):
                receiving = [receiving]

            return TradeProposal(giving=giving, receiving=receiving)
        except Exception as e:
            logger.error(f"Error parsing trade string: {e}")
            raise translate(e) from e
