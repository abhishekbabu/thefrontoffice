"""Several model providers behind one AnalysisModel, failing over between them.

Free tiers run out — by the minute on Groq, by the day on Gemini — and a
report should not fail because the first provider in the list is resting
when the second has quota to spare. So every call goes to the first provider
that is configured and not cooling down, and moves on when that one cannot
answer:

- a spent quota (a 429, or the 413 Groq gives a request too large for the
  tier) rests that provider for as long as it asked, or a minute;
- a rejected key or a failed answer moves on without resting it, so a key
  fixed in Settings is tried again on the very next call.

Names no vendor: `bootstrap` hands it the providers in order.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

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

DEFAULT_COOLDOWN_SECONDS = 60.0
"""Where a provider gives no Retry-After: Groq's limits are per minute."""

T = TypeVar("T")


class Cooldowns:
    """When each provider may be tried again.

    One instance outlives the requests that use it — a model is built per
    request, and a cooldown that forgot itself between them would send every
    report straight back into the same spent quota. Locked, because the web
    server answers on a thread pool.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def rest(self, provider: str, seconds: float) -> None:
        with self._lock:
            self._until[provider] = self._clock() + seconds

    def resting(self, provider: str) -> bool:
        with self._lock:
            return self._until.get(provider, 0.0) > self._clock()


class RoutedModel(AnalysisModel):
    """The configured providers, in order, as one model."""

    def __init__(self, models: list[tuple[str, AnalysisModel]], cooldowns: Cooldowns) -> None:
        self._models = models
        self._cooldowns = cooldowns

    @property
    def is_available(self) -> bool:
        return bool(self._configured())

    def _configured(self) -> list[tuple[str, AnalysisModel]]:
        return [(name, model) for name, model in self._models if getattr(model, "is_available", False)]

    def _order(self) -> list[tuple[str, AnalysisModel]]:
        """Rested providers first, in preference order; then the resting ones.

        A resting provider is tried last rather than never: a cooldown is a
        guess at when quota returns, and a stale guess beats a certain failure.
        """
        configured = self._configured()
        return [m for m in configured if not self._cooldowns.resting(m[0])] + [
            m for m in configured if self._cooldowns.resting(m[0])
        ]

    def attempt(self, call: Callable[[AnalysisModel], T]) -> T:
        """`call` on each provider in turn until one answers.

        Raises:
            AIUnavailableError: no provider is configured.
            AIKeyInvalidError, AIQuotaError, AIResponseError: every provider
                failed; the most actionable of their failures.
        """
        failures: list[tuple[str, FrontOfficeError]] = []
        for name, model in self._order():
            try:
                answer = call(model)
            except AIQuotaError as e:
                self._cooldowns.rest(name, e.retry_after or DEFAULT_COOLDOWN_SECONDS)
                logger.warning(f"{name} is out of quota; resting it and trying the next provider")
                failures.append((name, e))
            except (AIKeyInvalidError, AIResponseError) as e:
                logger.warning(f"{name} could not answer ({type(e).__name__}); trying the next provider")
                failures.append((name, e))
            else:
                if failures:
                    logger.info(f"Answered by {name} after {', '.join(n for n, _ in failures)} could not")
                return answer
        raise _verdict(failures)

    # ── the port ────────────────────────────────────────────────────

    # pyrefly: ignore[bad-override]  — identical generic signatures; see GeminiClient.
    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        return self.attempt(lambda model: model.generate_structured(prompt, schema))

    # pyrefly: ignore[bad-override]  — identical generic signatures; see GeminiClient.
    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        return self.attempt(lambda model: model.structure_text(text, schema, instruction))

    def parse_trade_string(self, text: str) -> TradeProposal:
        return self.attempt(lambda model: model.parse_trade_string(text))

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        if not self._configured():
            raise AIUnavailableError()
        return RoutedChat(self, initial_history or [], enable_search)


class RoutedChat:
    """A conversation that can change provider between turns.

    Holds its own transcript and opens a session on whichever provider is
    answering, seeded with all of it — the history is resent every turn
    anyway, so carrying on elsewhere costs nothing a turn did not already.
    """

    def __init__(self, router: RoutedModel, history: list[HistoryTurn], enable_search: bool) -> None:
        self._router = router
        self.transcript: list[HistoryTurn] = list(history)
        self._search = enable_search

    def send_message(self, message: str) -> object:
        def turn(model: AnalysisModel) -> object:
            reply = model.start_chat(initial_history=list(self.transcript), enable_search=self._search).send_message(
                message
            )
            if not getattr(reply, "text", None):
                raise AIResponseError("The model returned an empty answer.")
            return reply

        reply = self._router.attempt(turn)
        self.transcript += [
            HistoryTurn(role="user", parts=[message]),
            HistoryTurn(role="model", parts=[str(reply.text)]),
        ]
        return reply


# Most actionable first: a key is something to go and fix; a quota only waits.
_PRIORITY: tuple[type[FrontOfficeError], ...] = (AIKeyInvalidError, AIQuotaError, AIResponseError)


def _verdict(failures: list[tuple[str, FrontOfficeError]]) -> FrontOfficeError:
    """One error for a call every provider failed."""
    if not failures:
        return AIUnavailableError()
    quotas = [(name, e) for name, e in failures if isinstance(e, AIQuotaError)]
    if len(quotas) == len(failures) and len(quotas) > 1:
        names = ", ".join(name for name, _ in quotas)
        waits = [e.retry_after for _, e in quotas if e.retry_after]
        return AIQuotaError(
            provider=names,
            retry_after=min(waits) if waits else None,
            detail=f"Every configured model is out of quota ({names}). Analysis will work again once one resets.",
        )
    return min(failures, key=lambda f: next(i for i, kind in enumerate(_PRIORITY) if isinstance(f[1], kind)))[1]
