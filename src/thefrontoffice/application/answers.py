"""Every model answer, asked once per distinct input and kept.

On a free tier a call is the scarce thing, and most calls would get the same
answer they got last time: nothing the model would be shown has changed. So
each answer is kept under a scope naming what it is about, with a digest of
exactly what it was given. Asking again with the same input returns the kept
answer; asking with a changed input asks the model; and reading without
asking returns the kept answer either way, for the caller to mark stale.

The scope is as fine as the answer: a week's report is one answer per league,
and a free agent's call is one per player — so judging a page of them asks
only about the ones whose situation has moved.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from thefrontoffice.domain.models import Remembered
from thefrontoffice.domain.ports import AnswerStore, TModel


def digest(inputs: str) -> str:
    """What an answer was given, as something short enough to keep and compare."""
    return hashlib.sha256(inputs.encode("utf-8")).hexdigest()


class Answers:
    """The one way an engine asks the model for something worth keeping."""

    def __init__(self, store: AnswerStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._store = store
        self._clock = clock

    def latest(self, scope: str, schema: type[TModel]) -> Remembered[TModel] | None:
        """The kept answer, current or not, without asking anything."""
        return self._store.latest(scope, schema)

    def keep(self, scope: str, inputs: str, answer: TModel) -> Remembered[TModel]:
        """Keep `answer` as the one for `scope`, given `inputs`."""
        remembered = Remembered(answer=answer, inputs=digest(inputs), answered_at=self._clock())
        self._store.save(scope, remembered)
        return remembered

    def answer(self, scope: str, inputs: str, schema: type[TModel], ask: Callable[[], TModel]) -> Remembered[TModel]:
        """The kept answer where `inputs` is unchanged since; otherwise `ask()`, kept."""
        kept = self.latest(scope, schema)
        if kept is not None and is_current(kept, inputs):
            return kept
        return self.keep(scope, inputs, ask())


def is_current(remembered: Remembered[TModel], inputs: str) -> bool:
    """Whether `remembered` answered exactly `inputs`."""
    return remembered.inputs == digest(inputs)
