"""Tests for the OpenAI-compatible adapter: `llm/openai_compatible/client.py`.

The SDK client is a fake that records each request and replays scripted
answers or errors; the errors are the SDK's own classes, since telling them
apart is half of what the adapter does.
"""

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel

from thefrontoffice.adapters.outbound.llm.openai_compatible.client import OpenAICompatibleClient, Reply
from thefrontoffice.adapters.outbound.llm.openai_compatible.providers import Provider
from thefrontoffice.domain.errors import AIKeyInvalidError, AIQuotaError, AIResponseError, AIUnavailableError

PROVIDER = Provider(
    name="Groq",
    setting="GROQ_API_KEY",
    base_url="https://groq.example/v1",
    api_key="key",
    analysis_model="big",
    parsing_model="small",
)


class Verdict(BaseModel):
    call: str
    confidence: int


GOOD = json.dumps({"call": "start", "confidence": 3})


def _error(cls: type[openai.APIStatusError], status: int, message: str = "", **headers: str) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://groq.example/v1/chat/completions")
    return cls(message or f"{status}", response=httpx.Response(status, headers=headers, request=request), body=None)


def _format_refused() -> openai.APIStatusError:
    return _error(openai.BadRequestError, 400, "response_format json_schema is not supported by this model")


class FakeCompletions:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> Any:
        # Snapshotted, as the SDK serializes it: a chat keeps appending to the
        # same list, and a recorded reference would show turns sent later.
        self.requests.append({**request, "messages": [dict(m) for m in request["messages"]]})
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        message = SimpleNamespace(content=outcome)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def _model(*script: Any) -> tuple[OpenAICompatibleClient, FakeCompletions]:
    completions = FakeCompletions(list(script))
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatibleClient(PROVIDER, client=sdk), completions


def _formats(completions: FakeCompletions) -> list[str | None]:
    return [(r.get("response_format") or {}).get("type") for r in completions.requests]


# ── structured answers ──────────────────────────────────────────────────


def test_the_schema_is_enforced_by_the_model_where_it_can_be() -> None:
    model, completions = _model(GOOD)

    verdict = model.generate_structured("judge", Verdict)

    assert verdict == Verdict(call="start", confidence=3)
    [request] = completions.requests
    assert request["model"] == PROVIDER.analysis_model
    assert request["response_format"]["json_schema"]["schema"] == Verdict.model_json_schema()
    # Enforced in the request, so it is not also spent in the prompt.
    assert all("call" not in m["content"] for m in request["messages"])


def test_a_model_that_refuses_a_schema_is_given_it_in_words_and_asked_for_json() -> None:
    model, completions = _model(_format_refused(), GOOD)

    assert model.generate_structured("judge", Verdict).call == "start"
    assert _formats(completions) == ["json_schema", "json_object"]
    assert json.dumps(Verdict.model_json_schema()) in completions.requests[1]["messages"][0]["content"]


def test_a_model_with_no_json_mode_is_asked_plainly() -> None:
    model, completions = _model(_format_refused(), _format_refused(), GOOD)

    assert model.generate_structured("judge", Verdict).call == "start"
    assert _formats(completions) == ["json_schema", "json_object", None]


def test_an_answer_that_fails_the_schema_gets_one_repair_with_the_errors() -> None:
    model, completions = _model(json.dumps({"call": "start"}), GOOD)

    assert model.generate_structured("judge", Verdict).confidence == 3
    repair = completions.requests[1]
    assert "confidence" in repair["messages"][-1]["content"]
    # Repaired in the format the model already accepted.
    assert _formats(completions) == ["json_schema", "json_schema"]


def test_an_answer_still_wrong_after_its_repair_is_a_failed_call() -> None:
    model, _ = _model("{}", "{}")

    with pytest.raises(AIResponseError):
        model.generate_structured("judge", Verdict)


def test_json_inside_a_code_fence_is_read() -> None:
    model, _ = _model(f"```json\n{GOOD}\n```")

    assert model.generate_structured("judge", Verdict).call == "start"


def test_an_empty_answer_is_a_failed_call() -> None:
    model, _ = _model("")

    with pytest.raises(AIResponseError):
        model.generate_structured("judge", Verdict)


def test_prose_is_structured_by_the_fast_model() -> None:
    model, completions = _model(GOOD)

    model.structure_text("Start him.", Verdict, "Convert this.")

    assert completions.requests[0]["model"] == PROVIDER.parsing_model


def test_a_trade_is_parsed_into_its_two_sides_by_the_fast_model() -> None:
    model, completions = _model(json.dumps({"giving": ["Bijan Robinson"], "receiving": ["Puka Nacua"]}))

    proposal = model.parse_trade_string("Give Bijan, get Puka")

    assert (proposal.giving, proposal.receiving) == (["Bijan Robinson"], ["Puka Nacua"])
    assert completions.requests[0]["model"] == PROVIDER.parsing_model


# ── failures ────────────────────────────────────────────────────────────


def test_a_rejected_key_names_the_provider_and_the_setting_to_fix() -> None:
    model, _ = _model(_error(openai.AuthenticationError, 401))

    with pytest.raises(AIKeyInvalidError) as raised:
        model.generate_structured("judge", Verdict)
    assert raised.value.provider == PROVIDER.name
    assert PROVIDER.setting in str(raised.value)


def test_a_rate_limit_carries_how_long_the_provider_asked_to_wait() -> None:
    model, _ = _model(_error(openai.RateLimitError, 429, **{"retry-after": "12"}))

    with pytest.raises(AIQuotaError) as raised:
        model.generate_structured("judge", Verdict)
    assert (raised.value.provider, raised.value.retry_after) == (PROVIDER.name, 12.0)


def test_a_request_too_large_for_the_free_tier_is_a_quota_not_a_failure() -> None:
    """Groq answers 413 when one request exceeds the tier's tokens a minute —
    another provider can take it, which is what a quota error says."""
    model, _ = _model(_error(openai.APIStatusError, 413, "Request too large"))

    with pytest.raises(AIQuotaError):
        model.generate_structured("judge", Verdict)


def test_a_bad_request_that_is_not_about_the_format_is_not_retried_weaker() -> None:
    model, completions = _model(_error(openai.BadRequestError, 400, "model_not_found"))

    with pytest.raises(AIResponseError):
        model.generate_structured("judge", Verdict)
    assert len(completions.requests) == 1


def test_a_server_error_is_a_failed_call() -> None:
    model, _ = _model(_error(openai.InternalServerError, 500))

    with pytest.raises(AIResponseError):
        model.generate_structured("judge", Verdict)


def test_with_no_key_nothing_is_offered_and_nothing_is_called() -> None:
    model = OpenAICompatibleClient(replace(PROVIDER, api_key=None))

    assert not model.is_available
    with pytest.raises(AIUnavailableError):
        model.generate_structured("judge", Verdict)


# ── follow-up chats ─────────────────────────────────────────────────────


def test_a_chat_carries_its_seeded_history_and_every_turn_since() -> None:
    model, completions = _model("first answer", "second answer")
    chat = model.start_chat(initial_history=[{"role": "user", "parts": ["brief"]}, {"role": "model", "parts": ["{}"]}])

    chat.send_message("why?")
    reply = chat.send_message("and then?")

    assert isinstance(reply, Reply) and reply.text == "second answer"
    roles = [m["role"] for m in completions.requests[-1]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]


def test_asking_for_search_still_opens_a_chat() -> None:
    """Neither provider has web search; the prompt carries the news instead."""
    model, _ = _model("answer")

    reply = model.start_chat(enable_search=True).send_message("q")

    assert isinstance(reply, Reply) and reply.text == "answer"
