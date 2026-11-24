"""The players the manager will not let go, whatever the figures say.

A drop is chosen by worth, and worth is a reading of the past and a
projection: it cannot see a role about to grow, a rookie being brought on,
or a manager's own conviction. Marking a player untouchable is that
conviction, kept per league, and every chooser of a drop, a trade or a
transfer out reads it before it reads any figure.

Where one squad plays every league — FPL, whose mini-leagues are tables over
the same fifteen — the marks are kept per squad instead, so one mark holds in
each of them. Marks once kept per league there are moved onto the squad the
first time that league is read.

A mark on a player who has left your roster is dropped the next time the
marks are listed against it: it can change no choice — every chooser reads
your roster alone — and a list of names you no longer hold is only clutter.
A roster that will not load, or reads empty, prunes nothing.
"""

import logging
from collections.abc import Callable, Iterable

from thefrontoffice.application.answers import scope
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import UntouchableMark, Untouchables
from thefrontoffice.domain.ports import UntouchableStore

logger = logging.getLogger(__name__)

SQUAD = "squad"
"""The segment a squad's scope carries, so a squad id never reads as a league id that happens to match it."""


def untouchable_scope(key: str, league_id: str) -> str:
    """Where one league's untouchables are kept, under the competition's registry key."""
    return scope("untouchables", key, league_id)


def squad_scope(key: str, squad_id: str) -> str:
    """Where one squad's untouchables are kept, for a competition whose every league plays the same squad."""
    return scope("untouchables", key, SQUAD, squad_id)


class UntouchableMarks:
    """One competition's untouchables, per league or per squad: what its provider reads, and what the page marks."""

    def __init__(self, store: UntouchableStore, key: str, squad: Callable[[str], str] | None = None):
        """
        Args:
            squad: the squad a league is played with, where one squad plays every league; None keeps marks per league.
        """
        self._store = store
        self._key = key
        self._squad = squad

    def of(self, league_id: str) -> frozenset[str]:
        return frozenset(self._read(league_id)[1])

    def listed(self, league_id: str, held: Callable[[], Iterable[str]] | None = None) -> Untouchables:
        """Every untouchable, less any no longer on the roster `held` reads, where it reads one.

        `held` is asked only here, where the page lists the marks: a provider reading them already reads its
        own roster, and a mark outside it changes nothing there.
        """
        where, ids = self._read(league_id)
        roster = self._roster(held) if held is not None and ids else None
        if roster:
            kept = [pid for pid in ids if pid in roster]
            if kept != ids:
                logger.info(f"{self._key}: dropping marks on players no longer yours: {sorted(set(ids) - roster)}")
                self._store.save(where, kept)
                ids = kept
        return Untouchables(player_ids=ids)

    def mark(self, league_id: str, mark: UntouchableMark) -> Untouchables:
        """Mark one player untouchable or clear his mark; every untouchable in the league after it."""
        where, ids = self._read(league_id)
        ids = [pid for pid in ids if pid != mark.player_id]
        if mark.untouchable:
            ids.append(mark.player_id)
        self._store.save(where, ids)
        return Untouchables(player_ids=ids)

    def _read(self, league_id: str) -> tuple[str, list[str]]:
        """Where `league_id`'s marks are kept, and what is kept there, moving any kept per league onto its squad."""
        if self._squad is None:
            where = untouchable_scope(self._key, league_id)
            return where, self._store.player_ids(where)
        where = squad_scope(self._key, self._squad(league_id))
        ids = self._store.player_ids(where)
        former = untouchable_scope(self._key, league_id)
        if moved := self._store.player_ids(former):
            ids = [*ids, *(pid for pid in moved if pid not in ids)]
            self._store.save(where, ids)
            self._store.save(former, [])
        return where, ids

    def _roster(self, held: Callable[[], Iterable[str]]) -> set[str]:
        try:
            return set(held())
        except FrontOfficeError as e:
            logger.warning(f"{self._key}: keeping every untouchable, the roster would not load: {e}")
            return set()
