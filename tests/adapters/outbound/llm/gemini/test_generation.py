"""Tests for GeminiClient's generation paths, with a fake SDK client handed in."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types
from pydantic import BaseModel
from support.logs import capture_logs
from support.reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.outbound.llm.gemini.client import GeminiClient, translate
from thefrontoffice.adapters.outbound.llm.gemini.constants import MODEL_FLASH, MODEL_PRO
from thefrontoffice.domain.errors import AIKeyInvalidError, AIQuotaError, AIResponseError
from thefrontoffice.domain.models import ScoutReport, TradeVerdict

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
GEMINI_LOGGER = GeminiClient.__module__

BAD_KEY = errors.ClientError(
    400,
    {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
        }
    },
)
SPENT = errors.ClientError(429, {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}})
BROKEN = errors.ServerError(
    500,
    {"error": {"code": 500, "message": "{'@type': 'type.googleapis.com/google.rpc.ErrorInfo'}", "status": "INTERNAL"}},
)


def _response(
    parsed: BaseModel | None = None, text: str = "", usage: types.GenerateContentResponseUsageMetadata | None = None
) -> types.GenerateContentResponse:
    """A genai response as the SDK builds one: `parsed` where it validated, the raw text either way."""
    parts = [types.Part(text=text)] if text else []
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        parsed=parsed,
        usage_metadata=usage,
    )


class FakeModels:
    def __init__(self, response: types.GenerateContentResponse | None = None, error: Exception | None = None) -> None:
        self.response = response or _response()
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeChats:
    """Opens chats whose every turn is answered by `reply`."""

    def __init__(self, reply: Callable[[str], Any]) -> None:
        self.reply = reply

    def create(self, **kwargs: Any) -> Any:
        return SimpleNamespace(send_message=self.reply)


class FakeGenAI:
    """Stands in for genai.Client: the two namespaces the adapter calls."""

    def __init__(self, models: FakeModels | None = None, chats: FakeChats | None = None) -> None:
        self.models = models or FakeModels()
        self.chats = chats or FakeChats(lambda message: SimpleNamespace(text=""))


def _client(
    response: types.GenerateContentResponse | None = None, error: Exception | None = None
) -> tuple[GeminiClient, FakeModels]:
    models = FakeModels(response, error)
    return GeminiClient(client=FakeGenAI(models=models)), models


# ── generate_structured ─────────────────────────────────────────────────


def test_parsed_model_is_returned_directly() -> None:
    c, _ = _client(_response(MOCK_NBA_REPORT, "{}"))
    assert c.generate_structured("p", ScoutReport) == MOCK_NBA_REPORT


def test_reports_use_pro_and_request_a_json_schema() -> None:
    c, models = _client(_response(MOCK_NBA_REPORT, "{}"))
    c.generate_structured("p", ScoutReport)
    call = models.calls[0]
    assert call["model"] == MODEL_PRO
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_schema"] is ScoutReport


def test_raw_json_is_used_when_the_sdk_does_not_populate_parsed() -> None:
    """Guards against a client-library change degrading into a crash."""
    c, _ = _client(_response(text=MOCK_NBA_REPORT.model_dump_json()))
    assert c.generate_structured("p", ScoutReport) == MOCK_NBA_REPORT


def test_json_that_does_not_match_the_schema_raises() -> None:
    c, _ = _client(_response(text='{"matchup_insight": "x"}'))
    with pytest.raises(AIResponseError):
        c.generate_structured("p", ScoutReport)


def test_empty_response_raises() -> None:
    c, _ = _client(_response())
    with pytest.raises(AIResponseError):
        c.generate_structured("p", ScoutReport)


def test_api_failure_is_wrapped_as_a_domain_error() -> None:
    c, _ = _client(error=BROKEN)
    with pytest.raises(AIResponseError):
        c.generate_structured("p", ScoutReport)


def test_a_dropped_connection_is_a_failed_answer_another_provider_can_take() -> None:
    """The SDK raises its transport's own exceptions unwrapped."""
    c, _ = _client(error=ConnectionError("reset by peer"))
    with pytest.raises(AIResponseError):
        c.generate_structured("p", ScoutReport)


# ── structure_text ──────────────────────────────────────────────────────


def test_structuring_uses_flash_not_pro() -> None:
    """Converting prose is a parsing job — the cheap model, per project policy."""
    c, models = _client(_response(MOCK_NBA_VERDICT, "{}"))
    c.structure_text("some prose", TradeVerdict, instruction="Extract it.")
    assert models.calls[0]["model"] == MODEL_FLASH


def test_structuring_passes_the_prose_and_instruction_through() -> None:
    c, models = _client(_response(MOCK_NBA_VERDICT, "{}"))
    c.structure_text("VERDICT: accept", TradeVerdict, instruction="Extract it.")
    contents = models.calls[0]["contents"]
    assert "VERDICT: accept" in contents
    assert "Extract it." in contents


def test_structuring_is_held_to_the_schema() -> None:
    c, models = _client(_response(MOCK_NBA_VERDICT, "{}"))
    c.structure_text("prose", TradeVerdict, instruction="x")
    assert models.calls[0]["config"]["response_schema"] is TradeVerdict


def test_structuring_failure_is_wrapped() -> None:
    c, _ = _client(error=BROKEN)
    with pytest.raises(AIResponseError):
        c.structure_text("prose", TradeVerdict, instruction="x")


# ── usage logging ───────────────────────────────────────────────────────


def _usage(cached: int | None = None) -> types.GenerateContentResponseUsageMetadata:
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=3400, candidates_token_count=310, total_token_count=3710, cached_content_token_count=cached
    )


def test_token_usage_is_logged() -> None:
    """Gemini Pro on a large prompt is the only real expense; nothing else
    measures it."""
    c, _ = _client(_response(MOCK_NBA_REPORT, "{}", _usage()))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.generate_structured("p", ScoutReport)
    assert "3400 in" in logs.text
    assert "310 out" in logs.text
    assert MODEL_PRO in logs.text


def test_structuring_logs_against_flash() -> None:
    c, _ = _client(_response(MOCK_NBA_VERDICT, "{}", _usage()))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.structure_text("prose", TradeVerdict, instruction="x")
    assert MODEL_FLASH in logs.text


def test_missing_usage_metadata_still_returns_the_answer_and_logs_the_call() -> None:
    c, _ = _client(_response(MOCK_NBA_REPORT, "{}"))
    with capture_logs(GEMINI_LOGGER) as logs:
        result = c.generate_structured("p", ScoutReport)
    assert result == MOCK_NBA_REPORT
    assert MODEL_PRO in logs.text


def test_cached_tokens_are_reported_when_present() -> None:
    c, _ = _client(_response(MOCK_NBA_REPORT, "{}", _usage(cached=1200)))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.generate_structured("p", ScoutReport)
    assert "1200 cached" in logs.text


# ── what a person is told when the model refuses ────────────────────────


def test_a_rejected_key_is_named_as_such() -> None:
    """Distinct from having no key, which the app hides: something was
    configured and is wrong, and only the person who typed it can fix it."""
    error = translate(BAD_KEY)

    assert isinstance(error, AIKeyInvalidError)
    assert GeminiClient.key_setting in str(error)


def test_an_exhausted_quota_is_told_apart_from_a_bad_key() -> None:
    error = translate(SPENT)

    assert isinstance(error, AIQuotaError)
    assert error.provider == GeminiClient.name


def test_no_vendor_payload_reaches_the_message() -> None:
    """The SDK embeds a repr of a Google RPC payload — nested dicts, type URLs,
    a locale — which is unreadable anywhere a person is looking."""
    message = str(translate(BROKEN))

    assert "@type" not in message
    assert "googleapis" not in message
    assert "{" not in message


# ── chats ───────────────────────────────────────────────────────────────


def test_a_chat_failure_arrives_as_a_domain_error() -> None:
    """The SDK's chat raises its own exceptions; a spent quota has to be
    recognisable as one, or no other provider can take the turn."""

    def failing(message: str) -> Any:
        raise SPENT

    c = GeminiClient(client=FakeGenAI(chats=FakeChats(failing)))

    with pytest.raises(AIQuotaError):
        c.start_chat().send_message("why?")


def test_a_chat_answer_carries_the_model_text() -> None:
    c = GeminiClient(client=FakeGenAI(chats=FakeChats(lambda message: SimpleNamespace(text="because"))))

    assert c.start_chat().send_message("why?").text == "because"


@pytest.mark.parametrize("text", ["", None])
def test_a_chat_answer_with_nothing_said_is_a_failed_turn(text: str | None) -> None:
    """The SDK reports silence as None or empty; the port promises an answer."""
    c = GeminiClient(client=FakeGenAI(chats=FakeChats(lambda message: SimpleNamespace(text=text))))

    with pytest.raises(AIResponseError):
        c.start_chat().send_message("why?")
