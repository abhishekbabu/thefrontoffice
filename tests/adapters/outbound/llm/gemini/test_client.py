"""Tests for the Gemini client's availability, and how it names itself."""

import pytest
from support.reports import MOCK_NBA_VERDICT

from thefrontoffice.adapters.outbound.llm.gemini.client import GeminiClient, connect
from thefrontoffice.domain.errors import AIUnavailableError
from thefrontoffice.domain.models import ScoutReport, TradeVerdict

# ── with no key, the app has nothing to offer ───────────────────────────


def test_availability_is_readable_before_anything_is_offered() -> None:
    """A button that explains why it cannot be pressed has wasted the click."""
    assert GeminiClient(client=connect(None)).is_available is False
    assert GeminiClient(client=connect("a-key")).is_available is True


def test_every_entry_point_refuses_the_same_way_naming_its_key() -> None:
    """One domain error, so a caller never has to tell them apart."""
    client = GeminiClient(client=None)

    for call in (
        lambda: client.start_chat(),
        lambda: client.generate_structured("p", ScoutReport),
        lambda: client.structure_text(MOCK_NBA_VERDICT.model_dump_json(), TradeVerdict, "x"),
    ):
        with pytest.raises(AIUnavailableError) as raised:
            call()
        assert raised.value.keys == [client.key_setting]
