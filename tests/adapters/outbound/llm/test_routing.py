"""Tests for failing over between model providers: `llm/routing.py`.

Each provider is a fake that plays a script — an answer, or an error to raise
— and a clock the test moves by hand drives the cooldowns.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from thefrontoffice.adapters.outbound.llm.routing import DEFAULT_COOLDOWN_SECONDS, Cooldowns, RoutedModel
from thefrontoffice.domain.errors import AIKeyInvalidError, AIQuotaError, AIResponseError, AIUnavailableError
from thefrontoffice.domain.ports import ChatReply


class Answer(BaseModel):
    by: str


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Scripted:
    """One provider: answers as its name, unless the next outcome is an error."""

    def __init__(self, name: str, *outcomes: Exception, available: bool = True) -> None:
        self.name = name
        self.key_setting = f"{name.upper()}_API_KEY"
        self.outcomes = list(outcomes)
        self.is_available = available
        self.calls = 0
        self.histories: list[list[Any]] = []

    def _next(self) -> str:
        self.calls += 1
        if self.outcomes:
            raise self.outcomes.pop(0)
        return self.name

    def generate_structured(self, prompt: str, schema: type) -> Any:
        return Answer(by=self._next())

    def structure_text(self, text: str, schema: type, instruction: str) -> Any:
        return Answer(by=self._next())

    def start_chat(self, initial_history: Any = None, enable_search: bool = False) -> Any:
        self.histories.append(list(initial_history or []))
        return SimpleNamespace(send_message=lambda message: ChatReply(text=self._next()))


def _router(*providers: Scripted, clock: Clock | None = None) -> tuple[RoutedModel, Cooldowns]:
    cooldowns = Cooldowns(clock=clock or Clock())
    return RoutedModel(providers, cooldowns), cooldowns


def _ask(router: RoutedModel) -> str:
    return router.generate_structured("prompt", Answer).by


# ── which provider answers ──────────────────────────────────────────────


def test_the_first_configured_provider_answers() -> None:
    gemini, groq = Scripted("Gemini"), Scripted("Groq")
    router, _ = _router(gemini, groq)

    assert _ask(router) == "Gemini"
    assert groq.calls == 0


def test_a_provider_with_no_key_is_never_asked() -> None:
    gemini, groq = Scripted("Gemini", available=False), Scripted("Groq")
    router, _ = _router(gemini, groq)

    assert _ask(router) == "Groq"
    assert gemini.calls == 0


@pytest.mark.parametrize(
    "failure",
    [AIQuotaError("Gemini"), AIKeyInvalidError("Gemini", "GOOGLE_API_KEY"), AIResponseError()],
    ids=["quota", "bad-key", "failed-answer"],
)
def test_a_provider_that_cannot_answer_hands_over_to_the_next(failure: Exception) -> None:
    router, _ = _router(Scripted("Gemini", failure), Scripted("Groq"))

    assert _ask(router) == "Groq"


def test_every_port_method_fails_over() -> None:
    router, _ = _router(Scripted("Gemini", *[AIQuotaError("Gemini")] * 2), Scripted("Groq"))

    assert router.structure_text("prose", Answer, "convert").by == "Groq"
    assert router.generate_structured("prompt", Answer).by == "Groq"


# ── resting a spent quota ───────────────────────────────────────────────


def test_a_spent_quota_rests_the_provider_for_as_long_as_it_asked() -> None:
    clock = Clock()
    gemini, groq = Scripted("Gemini", AIQuotaError("Gemini", retry_after=30)), Scripted("Groq")
    router, _ = _router(gemini, groq, clock=clock)

    _ask(router)
    assert _ask(router) == "Groq"  # resting: not asked again
    assert gemini.calls == 1

    clock.now = 31
    assert _ask(router) == "Gemini"


def test_a_quota_with_no_wait_given_rests_a_default_while() -> None:
    clock = Clock()
    router, cooldowns = _router(Scripted("Groq", AIQuotaError("Groq")), Scripted("OpenRouter"), clock=clock)

    _ask(router)

    clock.now = DEFAULT_COOLDOWN_SECONDS - 1
    assert cooldowns.resting("Groq")
    clock.now = DEFAULT_COOLDOWN_SECONDS + 1
    assert not cooldowns.resting("Groq")


def test_a_rejected_key_is_not_rested_so_a_fixed_key_counts_at_once() -> None:
    router, cooldowns = _router(Scripted("Gemini", AIKeyInvalidError("Gemini", "GOOGLE_API_KEY")), Scripted("Groq"))

    _ask(router)

    assert not cooldowns.resting("Gemini")


def test_when_everything_is_resting_the_rested_are_tried_anyway() -> None:
    """A cooldown is a guess at when quota returns; a stale guess beats a certain failure."""
    router, cooldowns = _router(Scripted("Gemini"), Scripted("Groq"))
    cooldowns.rest("Gemini", 60)
    cooldowns.rest("Groq", 60)

    assert _ask(router) == "Gemini"


# ── when nobody can answer ──────────────────────────────────────────────


def test_with_no_provider_configured_the_model_is_unavailable() -> None:
    router, _ = _router(Scripted("Gemini", available=False))

    assert not router.is_available
    with pytest.raises(AIUnavailableError):
        _ask(router)
    with pytest.raises(AIUnavailableError):
        router.start_chat()


def test_an_unavailable_model_names_the_key_each_provider_reads() -> None:
    """The providers name their own settings; the domain error names none of its own."""
    router, _ = _router(Scripted("Gemini", available=False), Scripted("Groq", available=False))

    with pytest.raises(AIUnavailableError) as raised:
        _ask(router)
    assert raised.value.keys == ["GEMINI_API_KEY", "GROQ_API_KEY"]
    assert all(key in str(raised.value) for key in raised.value.keys)


def test_every_provider_out_of_quota_says_so_with_the_soonest_wait() -> None:
    router, _ = _router(
        Scripted("Gemini", AIQuotaError("Gemini", retry_after=90)),
        Scripted("Groq", AIQuotaError("Groq", retry_after=20)),
    )

    with pytest.raises(AIQuotaError) as raised:
        _ask(router)
    assert raised.value.retry_after == 20
    assert "Gemini" in raised.value.provider and "Groq" in raised.value.provider


def test_a_key_to_fix_outranks_a_quota_to_wait_out() -> None:
    """Only one of the two is something the person can do anything about."""
    router, _ = _router(
        Scripted("Gemini", AIQuotaError("Gemini")), Scripted("Groq", AIKeyInvalidError("Groq", "GROQ_API_KEY"))
    )

    with pytest.raises(AIKeyInvalidError) as raised:
        _ask(router)
    assert raised.value.provider == "Groq"


# ── conversations ───────────────────────────────────────────────────────


def test_a_chat_carries_on_with_the_next_provider_holding_the_whole_conversation() -> None:
    gemini, groq = Scripted("Gemini"), Scripted("Groq")
    router, _ = _router(gemini, groq)
    chat = router.start_chat(initial_history=[{"role": "user", "parts": ["brief"]}])

    chat.send_message("first?")
    gemini.outcomes.append(AIQuotaError("Gemini"))
    reply = chat.send_message("second?")

    assert reply.text == "Groq"
    # Groq was seeded with the brief and the first exchange.
    assert [turn["parts"][0] for turn in groq.histories[-1]] == ["brief", "first?", "Gemini"]


def test_a_chat_turn_with_no_answer_moves_on_like_a_failed_one() -> None:
    """A provider that said nothing raises; the next provider takes the turn."""
    router, _ = _router(Scripted("Gemini", AIResponseError("The model returned an empty answer.")), Scripted("Groq"))

    assert router.start_chat().send_message("q").text == "Groq"
