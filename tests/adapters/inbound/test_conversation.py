"""Tests for a conversation as the inbound adapters hold it: `adapters/inbound/conversation.py`."""

import pytest
from support.ai import FakeChat

from thefrontoffice.adapters.inbound.conversation import Conversation, Turn
from thefrontoffice.domain.errors import AIQuotaError, AIResponseError


def test_each_answered_question_is_kept_with_its_answer() -> None:
    conversation = Conversation(FakeChat(reply="Start him."))

    assert conversation.ask("Who starts?") == "Start him."
    assert conversation.turns == [Turn(role="you", text="Who starts?"), Turn(role="model", text="Start him.")]


def test_a_vendor_fault_becomes_a_model_failure_without_its_repr() -> None:
    conversation = Conversation(FakeChat(error=RuntimeError("<RpcError status=13 ...>")))

    with pytest.raises(AIResponseError) as raised:
        conversation.ask("Why?")

    assert "RpcError" not in str(raised.value)
    assert conversation.turns == []  # the model never took the question in


def test_a_failure_already_described_passes_through_as_itself() -> None:
    """ "Every model is out of quota" says more than "did not answer"."""
    with pytest.raises(AIQuotaError):
        Conversation(FakeChat(error=AIQuotaError("Gemini"))).ask("Why?")
