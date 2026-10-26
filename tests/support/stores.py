"""In-memory stand-ins for what the app keeps on disk: model answers and item decisions."""

from typing import Any


class FakeItemStates:
    """Stands in for the item-state store: each league's decisions, in memory."""

    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}

    def states(self, scope: str) -> dict[str, Any]:
        return dict(self.saved.get(scope, {}))

    def save(self, scope: str, states: dict[str, Any]) -> None:
        self.saved[scope] = dict(states)


class FakeAnswers:
    """Stands in for the answer store: each scope's latest, in memory."""

    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}

    def latest(self, scope: str, schema: type) -> Any:
        return self.saved.get(scope)

    def save(self, scope: str, remembered: Any) -> None:
        self.saved[scope] = remembered
