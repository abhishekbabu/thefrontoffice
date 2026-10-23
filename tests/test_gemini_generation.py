"""Tests for GeminiClient's structured-generation paths, with a fake SDK client."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import capture_logs
from reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.outbound.llm.gemini.client import GeminiClient
from thefrontoffice.adapters.outbound.llm.gemini.constants import MODEL_FLASH, MODEL_PRO
from thefrontoffice.domain.errors import AIResponseError, AIUnavailableError
from thefrontoffice.domain.models import ScoutReport, TradeVerdict

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
GEMINI_LOGGER = GeminiClient.__module__


class FakeModels:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
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


def _client(response: Any = None, error: Exception | None = None) -> tuple[GeminiClient, FakeModels]:
    c = GeminiClient(api_key="fake-key")
    models = FakeModels(response, error)
    c.client = FakeGenAI(models=models)
    return c, models


# ── generate_structured ─────────────────────────────────────────────────


def test_parsed_model_is_returned_directly() -> None:
    c, _ = _client(SimpleNamespace(parsed=MOCK_NBA_REPORT, text="{}"))
    assert c.generate_structured("p", ScoutReport) == MOCK_NBA_REPORT


def test_reports_use_pro_and_request_a_json_schema() -> None:
    c, models = _client(SimpleNamespace(parsed=MOCK_NBA_REPORT, text="{}"))
    c.generate_structured("p", ScoutReport)
    call = models.calls[0]
    assert call["model"] == MODEL_PRO
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_schema"] is ScoutReport


def test_raw_json_is_used_when_the_sdk_does_not_populate_parsed() -> None:
    """Guards against a client-library change degrading into a crash."""
    c, _ = _client(SimpleNamespace(parsed=None, text=MOCK_NBA_REPORT.model_dump_json()))
    assert c.generate_structured("p", ScoutReport) == MOCK_NBA_REPORT


def test_json_that_does_not_match_the_schema_raises() -> None:
    c, _ = _client(SimpleNamespace(parsed=None, text='{"matchup_insight": "x"}'))
    with pytest.raises(AIResponseError, match="did not fit the expected shape"):
        c.generate_structured("p", ScoutReport)


def test_empty_response_raises() -> None:
    c, _ = _client(SimpleNamespace(parsed=None, text=""))
    with pytest.raises(AIResponseError, match="nothing usable"):
        c.generate_structured("p", ScoutReport)


def test_api_failure_is_wrapped_as_a_domain_error() -> None:
    c, _ = _client(error=RuntimeError("503 backend error"))
    with pytest.raises(AIResponseError, match="did not return a usable answer"):
        c.generate_structured("p", ScoutReport)


def test_missing_credentials_raise_before_any_call() -> None:
    c = GeminiClient(api_key=None)
    with pytest.raises(AIUnavailableError):
        c.generate_structured("p", ScoutReport)


# ── structure_text ──────────────────────────────────────────────────────


def test_structuring_uses_flash_not_pro() -> None:
    """Converting prose is a parsing job — the cheap model, per project policy."""
    c, models = _client(SimpleNamespace(parsed=MOCK_NBA_VERDICT, text="{}"))
    c.structure_text("some prose", TradeVerdict, instruction="Extract it.")
    assert models.calls[0]["model"] == MODEL_FLASH


def test_structuring_passes_the_prose_and_instruction_through() -> None:
    c, models = _client(SimpleNamespace(parsed=MOCK_NBA_VERDICT, text="{}"))
    c.structure_text("VERDICT: accept", TradeVerdict, instruction="Extract it.")
    contents = models.calls[0]["contents"]
    assert "VERDICT: accept" in contents
    assert "Extract it." in contents
    assert "verbatim" in contents  # the do-not-editorialise instruction


def test_structuring_failure_is_wrapped() -> None:
    c, _ = _client(error=RuntimeError("bad request"))
    with pytest.raises(AIResponseError, match="did not return a usable answer"):
        c.structure_text("prose", TradeVerdict, instruction="x")


def test_structuring_without_credentials_raises() -> None:
    c = GeminiClient(api_key=None)
    with pytest.raises(AIUnavailableError):
        c.structure_text("prose", TradeVerdict, instruction="x")


# ── parse_trade_string ──────────────────────────────────────────────────


def test_trade_parsing_returns_both_sides() -> None:
    c, _ = _client(SimpleNamespace(text='{"giving": ["A"], "receiving": ["B"]}'))
    proposal = c.parse_trade_string("Give A, Get B")
    assert proposal.giving == ["A"]
    assert proposal.receiving == ["B"]
    assert proposal.is_valid


def test_trade_parsing_coerces_a_bare_string_into_a_list() -> None:
    """The model sometimes returns a string when only one player is involved."""
    c, _ = _client(SimpleNamespace(text='{"giving": "A", "receiving": "B"}'))
    proposal = c.parse_trade_string("Give A, Get B")
    assert proposal.giving == ["A"]
    assert proposal.receiving == ["B"]


def test_trade_parsing_failure_raises() -> None:
    c, _ = _client(error=RuntimeError("boom"))
    with pytest.raises(AIResponseError, match="did not return a usable answer"):
        c.parse_trade_string("x")


def test_unparseable_json_raises_rather_than_returning_an_empty_trade() -> None:
    c, _ = _client(SimpleNamespace(text="not json at all"))
    with pytest.raises(AIResponseError):
        c.parse_trade_string("x")


# ── usage logging ───────────────────────────────────────────────────────


class Usage:
    prompt_token_count = 3400
    candidates_token_count = 310
    total_token_count = 3710
    cached_content_token_count = 0


def test_token_usage_is_logged() -> None:
    """Gemini Pro on a large prompt is the only real expense; nothing else
    measures it."""
    c, _ = _client(SimpleNamespace(parsed=MOCK_NBA_REPORT, text="{}", usage_metadata=Usage()))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.generate_structured("p", ScoutReport)
    assert "3400 in" in logs.text
    assert "310 out" in logs.text
    assert MODEL_PRO in logs.text


def test_structuring_logs_against_flash() -> None:
    c, _ = _client(SimpleNamespace(parsed=MOCK_NBA_VERDICT, text="{}", usage_metadata=Usage()))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.structure_text("prose", TradeVerdict, instruction="x")
    assert MODEL_FLASH in logs.text


def test_missing_usage_metadata_still_logs_latency() -> None:
    """An SDK change that drops usage_metadata must not break the call."""
    c, _ = _client(SimpleNamespace(parsed=MOCK_NBA_REPORT, text="{}"))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.generate_structured("p", ScoutReport)
    assert "no usage metadata" in logs.text


def test_cached_tokens_are_reported_when_present() -> None:
    class Cached(Usage):
        cached_content_token_count = 1200

    c, _ = _client(SimpleNamespace(parsed=MOCK_NBA_REPORT, text="{}", usage_metadata=Cached()))
    with capture_logs(GEMINI_LOGGER) as logs:
        c.generate_structured("p", ScoutReport)
    assert "1200 cached" in logs.text


# ── what a person is told when the model refuses ────────────────────────


def test_a_rejected_key_is_named_as_such() -> None:
    """Distinct from having no key, which the app hides: something was
    configured and is wrong, and only the person who typed it can fix it."""
    from thefrontoffice.adapters.outbound.llm.gemini.client import translate
    from thefrontoffice.domain.errors import AIKeyInvalidError

    error = translate(Exception("400 INVALID_ARGUMENT ... 'reason': 'API_KEY_INVALID' ..."))

    assert isinstance(error, AIKeyInvalidError)
    assert error.code == "ai_key_invalid"


def test_an_exhausted_quota_is_told_apart_from_a_bad_key() -> None:
    from thefrontoffice.adapters.outbound.llm.gemini.client import translate
    from thefrontoffice.domain.errors import AIQuotaError

    assert isinstance(translate(Exception("429 RESOURCE_EXHAUSTED")), AIQuotaError)


def test_no_vendor_payload_reaches_the_message() -> None:
    """The SDK embeds a repr of a Google RPC payload — nested dicts, type URLs,
    a locale — which is unreadable anywhere a person is looking."""
    from thefrontoffice.adapters.outbound.llm.gemini.client import translate

    raw = "500 INTERNAL {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.ErrorInfo'}]}}"
    message = str(translate(Exception(raw)))

    assert "@type" not in message
    assert "googleapis" not in message
    assert "{" not in message


# ── chats ───────────────────────────────────────────────────────────────


def test_a_chat_failure_arrives_as_a_domain_error() -> None:
    """The SDK's chat raises its own exceptions; a spent quota has to be
    recognisable as one, or no other provider can take the turn."""
    from thefrontoffice.domain.errors import AIQuotaError

    def failing(message: str) -> Any:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    c = GeminiClient(api_key="fake-key")
    c.client = FakeGenAI(chats=FakeChats(failing))

    with pytest.raises(AIQuotaError):
        c.start_chat().send_message("why?")


def test_a_chat_answer_passes_through_untouched() -> None:
    reply = SimpleNamespace(text="because")
    c = GeminiClient(api_key="fake-key")
    c.client = FakeGenAI(chats=FakeChats(lambda message: reply))

    assert c.start_chat().send_message("why?") is reply
