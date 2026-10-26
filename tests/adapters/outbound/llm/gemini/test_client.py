"""Tests for the Gemini client's availability, and which model it uses where."""

import pytest

from thefrontoffice.adapters.outbound.llm.gemini.client import GeminiClient
from thefrontoffice.domain.errors import AIUnavailableError
from thefrontoffice.domain.models import ScoutReport

# ── with no key, the app has nothing to offer ───────────────────────────


def test_availability_is_readable_before_anything_is_offered() -> None:
    """A button that explains why it cannot be pressed has wasted the click."""
    assert GeminiClient(api_key=None).is_available is False
    assert GeminiClient(api_key="a-key").is_available is True


def test_the_key_is_read_at_construction_not_bound_as_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key saved in Settings must take effect on the next call, not the next
    restart — a default argument is evaluated once, at import."""
    from thefrontoffice.config.settings import settings

    monkeypatch.setattr(settings, "gemini_api_key", "set-after-import")

    assert GeminiClient().is_available


def test_every_entry_point_refuses_the_same_way() -> None:
    """One domain error, so a caller never has to tell them apart."""
    client = GeminiClient(api_key=None)

    for call in (
        lambda: client.start_chat(),
        lambda: client.generate_structured("p", ScoutReport),
        lambda: client.parse_trade_string("Give A, Get B"),
    ):
        with pytest.raises(AIUnavailableError):
            call()


# ── which model does what ───────────────────────────────────────────────
