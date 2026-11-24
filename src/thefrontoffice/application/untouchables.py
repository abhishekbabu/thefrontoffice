"""The players the manager will not let go, whatever the figures say.

A drop is chosen by worth, and worth is a reading of the past and a
projection: it cannot see a role about to grow, a rookie being brought on,
or a manager's own conviction. Marking a player untouchable is that
conviction, kept per league, and every chooser of a drop, a trade or a
transfer out reads it before it reads any figure.
"""

from thefrontoffice.application.answers import scope
from thefrontoffice.domain.models import UntouchableMark, Untouchables
from thefrontoffice.domain.ports import UntouchableStore


def untouchable_scope(key: str, league_id: str) -> str:
    """Where one league's untouchables are kept, under the competition's registry key."""
    return scope("untouchables", key, league_id)


class UntouchableMarks:
    """One competition's untouchables, per league: what its provider reads, and what the page marks."""

    def __init__(self, store: UntouchableStore, key: str):
        self._store = store
        self._key = key

    def of(self, league_id: str) -> frozenset[str]:
        return frozenset(self._store.player_ids(untouchable_scope(self._key, league_id)))

    def listed(self, league_id: str) -> Untouchables:
        return Untouchables(player_ids=self._store.player_ids(untouchable_scope(self._key, league_id)))

    def mark(self, league_id: str, mark: UntouchableMark) -> Untouchables:
        """Mark one player untouchable or clear his mark; every untouchable in the league after it."""
        where = untouchable_scope(self._key, league_id)
        ids = [pid for pid in self._store.player_ids(where) if pid != mark.player_id]
        if mark.untouchable:
            ids.append(mark.player_id)
        self._store.save(where, ids)
        return Untouchables(player_ids=ids)
