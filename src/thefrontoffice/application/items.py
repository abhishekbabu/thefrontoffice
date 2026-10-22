"""The manager's own decisions about the week's to-do items.

The list clears an item by itself when league state settles it — the swap
made, the player back. What it cannot see is a decision not to act ("I'm
keeping Bernard in") or not yet ("after his status on Sunday"). Without
somewhere to say so, an item already weighed keeps the top of the list.

So an item can be dismissed — hidden while it reads as it did, back the
moment it changes — or snoozed until a time. Hidden items are marked rather
than dropped, so the page can still offer them back.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from thefrontoffice.domain.errors import ItemDecisionError
from thefrontoffice.domain.models import Action, ItemDecision, ItemState, answer_scope
from thefrontoffice.domain.ports import ItemStateStore


def item_scope(competition: str, league_id: str) -> str:
    """Where one league's decisions are kept."""
    return answer_scope("items", competition, league_id)


def apply_decisions(actions: list[Action], states: dict[str, ItemState], now: datetime) -> list[Action]:
    """Every item, in order, marked by what the manager decided about it.

    A snooze that has run out no longer hides anything. A dismissal hides an
    item only while it still has the fingerprint it was dismissed with; one
    that has changed since comes back, saying so.
    """
    marked = []
    for action in actions:
        state = states.get(action.key)
        if state is None or not action.key:
            marked.append(action)
        elif state.snoozed_until is not None and state.snoozed_until > now:
            marked.append(action.model_copy(update={"hidden": "snoozed", "snoozed_until": state.snoozed_until}))
        elif state.dismissed_as and state.dismissed_as == action.fingerprint:
            marked.append(action.model_copy(update={"hidden": "dismissed"}))
        elif state.dismissed_as:
            marked.append(action.model_copy(update={"resurfaced": True}))
        else:
            marked.append(action)
    return marked


class ItemDecisions:
    """Keeps decisions per league and applies them to the week's items."""

    def __init__(self, store: ItemStateStore, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._store = store
        self._clock = clock

    def apply(self, competition: str, league_id: str, actions: list[Action]) -> list[Action]:
        return apply_decisions(actions, self._store.states(item_scope(competition, league_id)), self._clock())

    def decide(self, competition: str, league_id: str, decision: ItemDecision) -> ItemState | None:
        """Keep `decision`, replacing any earlier one on the same item; None once restored.

        Raises:
            ItemDecisionError: a snooze that ends in the past.
        """
        scope = item_scope(competition, league_id)
        states = self._store.states(scope)
        if decision.decision == "restore":
            states.pop(decision.key, None)
            self._store.save(scope, states)
            return None
        if decision.decision == "snooze":
            assert decision.until is not None  # the model validates it
            until = decision.until.astimezone(timezone.utc)
            if until <= self._clock():
                raise ItemDecisionError("A snooze has to end in the future.")
            state = ItemState(key=decision.key, snoozed_until=until)
        else:
            state = ItemState(key=decision.key, dismissed_as=decision.fingerprint)
        states[decision.key] = state
        self._store.save(scope, states)
        return state
