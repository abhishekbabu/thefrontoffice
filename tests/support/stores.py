"""In-memory stand-ins for what the app keeps on disk: model answers and item decisions.

Each keeps what it is handed as the disk stores do — as JSON, read back
through the schema asked for — so a test cannot pass by reading back an
object the real store would have had to parse.
"""

from thefrontoffice.domain.models import ItemState, Remembered
from thefrontoffice.domain.ports import TModel

type Json = dict[str, object]


class FakeItemStates:
    """Stands in for the item-state store: each league's decisions, in memory."""

    def __init__(self) -> None:
        self._saved: dict[str, dict[str, Json]] = {}

    def states(self, scope: str) -> dict[str, ItemState]:
        return {key: ItemState.model_validate(value) for key, value in self._saved.get(scope, {}).items()}

    def save(self, scope: str, states: dict[str, ItemState]) -> None:
        self._saved[scope] = {key: state.model_dump(mode="json") for key, state in states.items()}


class FakeAnswers:
    """Stands in for the answer store: each scope's latest, in memory."""

    def __init__(self) -> None:
        self._saved: dict[str, Json] = {}

    def latest(self, scope: str, schema: type[TModel]) -> Remembered[TModel] | None:
        stored = self._saved.get(scope)
        return Remembered[schema].model_validate(stored) if stored is not None else None

    def save(self, scope: str, remembered: Remembered[TModel]) -> None:
        self._saved[scope] = remembered.model_dump(mode="json")
