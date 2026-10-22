"""The AnalysisModel port over any OpenAI-compatible chat API.

Groq and OpenRouter both speak the OpenAI wire format, so one adapter serves
both, parameterised by a `Provider`. What they do not share with Gemini is a
guarantee of shape: Gemini enforces a response schema itself, while here
support varies by model — some enforce a JSON schema, some only promise JSON,
some promise nothing. So the schema is asked for in the strongest form the
model accepts, and the answer is always validated against the Pydantic model,
with one chance to repair it before the call is reported as failed.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import openai
from pydantic import BaseModel, Field, ValidationError

from thefrontoffice.adapters.outbound.llm.openai_compatible.providers import Provider
from thefrontoffice.domain.errors import (
    AIKeyInvalidError,
    AIQuotaError,
    AIResponseError,
    AIUnavailableError,
    FrontOfficeError,
)
from thefrontoffice.domain.models import TradeProposal
from thefrontoffice.domain.ports import AnalysisModel, ChatSession, HistoryTurn, TModel

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120
# One retry for a dropped connection or a 5xx. Not more: on a rate limit the
# right move is another provider, not a longer wait on this one.
MAX_RETRIES = 1

SCHEMA_INSTRUCTION = (
    "Answer with a single JSON object and nothing else — no prose, no code fence. "
    "It must validate against this JSON Schema:\n{schema}"
)
REPAIR_INSTRUCTION = (
    "That answer did not validate against the schema:\n{errors}\n\n"
    "Return the corrected JSON object only, changing nothing the errors do not require."
)
TRADE_INSTRUCTION = (
    'Extract the players being given and received in this trade offer, using full player names.\n\nTrade: "{text}"'
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def translate(error: Exception, provider: Provider) -> FrontOfficeError:
    """Turn an SDK failure into one of the three things worth telling apart.

    A rejected key is something to go and fix; a spent quota — or a request
    the free tier calls too large, which Groq answers with 413 — is something
    another provider can absorb; anything else is a failed answer.
    """
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return AIKeyInvalidError(provider.name, provider.setting)
    status = getattr(error, "status_code", None)
    if isinstance(error, openai.RateLimitError) or status == 413:
        return AIQuotaError(provider.name, retry_after=_retry_after(error))
    return AIResponseError()


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    value = getattr(response, "headers", {}).get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rejects_format(error: Exception) -> bool:
    """Whether a 400 is the model refusing a `response_format`, rather than the request."""
    text = str(error).lower()
    return isinstance(error, openai.BadRequestError) and any(
        word in text for word in ("response_format", "json_schema", "structured", "json mode", "json_object")
    )


class _TradeSides(BaseModel):
    """The shape a trade is parsed into. TradeProposal is a dataclass, not a schema."""

    giving: list[str] = Field(description="Full names of the players being given away.")
    receiving: list[str] = Field(description="Full names of the players being received.")


@dataclass(frozen=True)
class Reply:
    """What a chat turn returns: the text, as Gemini's response carries it."""

    text: str


class OpenAICompatibleChat:
    """A follow-up conversation, holding its own history.

    Kept here rather than on the server because the server keeps none: every
    turn resends the whole conversation, which is also what lets a later
    turn carry on with a different provider.
    """

    def __init__(self, model: "OpenAICompatibleClient", messages: list[dict[str, str]]) -> None:
        self._model = model
        self.messages = messages

    def send_message(self, message: str) -> Reply:
        self.messages.append({"role": "user", "content": message})
        text = self._model.complete(self._model.provider.analysis_model, self.messages)
        self.messages.append({"role": "assistant", "content": text})
        return Reply(text=text)


class OpenAICompatibleClient(AnalysisModel):
    """One OpenAI-compatible provider, as the AnalysisModel port.

    Inherits the protocol explicitly, as GeminiClient does, so a drift between
    the two fails the type check here rather than at a caller.
    """

    def __init__(self, provider: Provider, client: Any = None) -> None:
        self.provider = provider
        self.client = client or (
            openai.OpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,
            )
            if provider.api_key
            else None
        )

    @property
    def is_available(self) -> bool:
        return self.client is not None

    # ── the port ────────────────────────────────────────────────────

    # pyrefly: ignore[bad-override]  — identical generic signatures; see GeminiClient.
    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        """An analysis, from the strong model, validated against `schema`."""
        return self._structured(self.provider.analysis_model, prompt, schema)

    # pyrefly: ignore[bad-override]  — identical generic signatures; see GeminiClient.
    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        """Prose already written, put into `schema` by the fast model without changing it."""
        prompt = (
            f"{instruction}\n\nConvert the following analysis verbatim — do not add, drop or soften anything:\n\n{text}"
        )
        return self._structured(self.provider.parsing_model, prompt, schema)

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        """A conversation seeded with `initial_history`.

        `enable_search` is accepted and cannot be honoured: neither provider
        offers web search. The prompts carry the news themselves, which is
        what search was asked for.
        """
        self._require_client()
        if enable_search:
            logger.info(f"{self.provider.name} has no web search; answering from the prompt alone.")
        messages = [
            {"role": "assistant" if turn["role"] == "model" else "user", "content": "\n".join(turn["parts"])}
            for turn in initial_history or []
        ]
        return OpenAICompatibleChat(self, messages)

    def parse_trade_string(self, text: str) -> TradeProposal:
        """The two sides of a trade typed in prose, by the fast model."""
        sides = self._structured(self.provider.parsing_model, TRADE_INSTRUCTION.format(text=text), _TradeSides)
        return TradeProposal(giving=sides.giving, receiving=sides.receiving)

    # ── the wire ────────────────────────────────────────────────────

    def _require_client(self) -> Any:
        if self.client is None:
            raise AIUnavailableError()
        return self.client

    def complete(
        self, model: str, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None
    ) -> str:
        """One chat completion's text, with SDK failures translated.

        Raises:
            AIUnavailableError: no key for this provider.
            AIKeyInvalidError, AIQuotaError, AIResponseError: as `translate` sorts them.
        """
        client = self._require_client()
        extra = {"response_format": response_format} if response_format else {}
        try:
            started = time.perf_counter()
            response = client.chat.completions.create(model=model, messages=messages, **extra)
            self._log_usage(model, response, time.perf_counter() - started)
        except openai.BadRequestError as e:
            # Only a refused format is the caller's to handle — it will try a
            # weaker one. Every other refusal is a failed call like any other.
            if response_format and _rejects_format(e):
                raise
            logger.error(f"{self.provider.name} rejected the request: {e}")
            raise translate(e, self.provider) from e
        except openai.OpenAIError as e:
            logger.error(f"{self.provider.name} call failed: {e}")
            raise translate(e, self.provider) from e

        choices = getattr(response, "choices", None) or []
        text = choices[0].message.content if choices else None
        if not text:
            raise AIResponseError("The model returned nothing usable. Try again.")
        return text

    def _structured(self, model: str, prompt: str, schema: type[TModel]) -> TModel:
        """Ask in the strongest form the model accepts; validate; repair once."""
        messages, raw, accepted = self._first_answer(model, prompt, schema)
        try:
            return schema.model_validate_json(_unfenced(raw))
        except ValidationError as e:
            logger.warning(f"{self.provider.name} {model} answer failed {schema.__name__}; asking once to repair it")
            errors = e
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": REPAIR_INSTRUCTION.format(errors=errors)},
        ]
        # The format the model has already accepted; the strongest one may not be.
        repaired = self.complete(model, messages, accepted)
        try:
            return schema.model_validate_json(_unfenced(repaired))
        except ValidationError as e:
            logger.error(f"{self.provider.name} {model} answer still failed {schema.__name__}: {e}")
            raise AIResponseError("The model's answer did not fit the expected shape. Try again.") from e

    def _first_answer(
        self, model: str, prompt: str, schema: type[TModel]
    ) -> tuple[list[dict[str, str]], str, dict[str, Any] | None]:
        """The first answer, the conversation that produced it, and the format it accepted.

        The schema goes in the request rather than the prompt where the model
        enforces it, which keeps it out of the token budget a free tier counts.
        Where it is refused, the schema moves into a system instruction and
        the request asks for JSON — and failing even that, for anything.
        """
        user = {"role": "user", "content": prompt}
        enforced = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False},
        }
        try:
            return [user], self.complete(model, [user], enforced), enforced
        except openai.BadRequestError:
            logger.info(f"{self.provider.name} {model} does not enforce a schema; describing it instead")

        described = [
            {"role": "system", "content": SCHEMA_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema()))},
            user,
        ]
        json_mode = {"type": "json_object"}
        try:
            return described, self.complete(model, described, json_mode), json_mode
        except openai.BadRequestError:
            logger.info(f"{self.provider.name} {model} has no JSON mode; relying on the instruction")
        return described, self.complete(model, described), None

    @staticmethod
    def _log_usage(model: str, response: object, elapsed: float) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            logger.info(f"{model} responded in {elapsed:.2f}s (no usage reported)")
            return
        logger.info(
            f"{model} responded in {elapsed:.2f}s — {getattr(usage, 'prompt_tokens', None)} in, "
            f"{getattr(usage, 'completion_tokens', None)} out, {getattr(usage, 'total_tokens', None)} total"
        )


def _unfenced(text: str) -> str:
    """The JSON inside a ```json fence, which models add however they are asked."""
    return _FENCE.sub("", text.strip())
