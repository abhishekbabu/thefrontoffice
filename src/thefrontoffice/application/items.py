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
from datetime import UTC, datetime

from thefrontoffice.application.answers import scope
from thefrontoffice.domain.errors import ItemDecisionError
from thefrontoffice.domain.models import Action, ItemDecision, ItemMark, ItemState
from thefrontoffice.domain.ports import ItemStateStore


def item_scope(key: str, league_id: str) -> str:
    """Where one league's decisions are kept, under the competition's registry key."""
    return scope("items", key, league_id)


def mark(fingerprint: str, state: ItemState, now: datetime) -> ItemMark:
    """What `state` makes of an item that reads as `fingerprint` at `now`.

    A snooze that has run out no longer hides anything. A dismissal hides an
    item only while it still has the fingerprint it was dismissed with; one
    that has changed since comes back, saying so.
    """
    if state.snoozed_until is not None and state.snoozed_until > now:
        return ItemMark(hidden="snoozed", snoozed_until=state.snoozed_until)
    if state.dismissed_as and state.dismissed_as == fingerprint:
        return ItemMark(hidden="dismissed")
    return ItemMark(resurfaced=bool(state.dismissed_as))


def apply_decisions(actions: list[Action], states: dict[str, ItemState], now: datetime) -> list[Action]:
    """Every item, in order, marked by what the manager decided about it."""
    return [
        action.model_copy(update={"mark": mark(action.fingerprint, state, now)})
        if action.key and (state := states.get(action.key)) is not None
        else action
        for action in actions
    ]


class ItemDecisions:
    """Keeps decisions per league and applies them to the week's items."""

    def __init__(self, store: ItemStateStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._store = store
        self._clock = clock

    def apply(self, key: str, league_id: str, actions: list[Action]) -> list[Action]:
        return apply_decisions(actions, self._store.states(item_scope(key, league_id)), self._clock())

    def decide(self, key: str, league_id: str, decision: ItemDecision) -> ItemMark:
        """Keep `decision`, replacing any earlier one on the same item; what it makes of the item.

        The item is the one the decision was made on — for a dismissal, the
        fingerprint it names — so the page can show the answer without
        re-reading the week.

        Raises:
            ItemDecisionError: a snooze that ends in the past.
        """
        scope = item_scope(key, league_id)
        states = self._store.states(scope)
        now = self._clock()
        if decision.decision == "restore":
            states.pop(decision.key, None)
            self._store.save(scope, states)
            return ItemMark()
        if decision.decision == "snooze":
            assert decision.until is not None  # the model validates it
            until = decision.until.astimezone(UTC)
            if until <= now:
                raise ItemDecisionError("A snooze has to end in the future.")
            state = ItemState(key=decision.key, snoozed_until=until)
        else:
            state = ItemState(key=decision.key, dismissed_as=decision.fingerprint)
        states[decision.key] = state
        self._store.save(scope, states)
        return mark(decision.fingerprint, state, now)
