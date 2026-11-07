"""Scopes kept under a competition's former name, still found under its current one.

Kept answers and to-do decisions were once filed under a competition's
display label — `scout:NFL (Sleeper):<league>` — and are now filed under its
registry key, `scout:nfl-sleeper:<league>`. A store reading a scope it has
nothing under looks once more under the former name, and files what it finds
under the current one, so no kept judgment or dismissal is lost to the rename.
"""

from datetime import timedelta
from typing import Any

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.application.answers import parts
from thefrontoffice.application.answers import scope as make_scope

FORMER_NAMES = {
    "nba-yahoo": "NBA (Yahoo)",
    "nfl-sleeper": "NFL (Sleeper)",
    "premier-league-fpl": "FPL (Fantasy Premier League)",
}
"""Each registry key's label as it read when things were filed under it.

History, so spelled out rather than read off the registry, whose labels are free
to change: a competition added since was never filed under a label at all.
"""


def former(scope: str) -> str | None:
    """`scope` as it was spelled before its competition was renamed; None where it never was."""
    taken = parts(scope)
    if taken is None:
        return None
    kind, competition, about = taken
    old = FORMER_NAMES.get(competition)
    return make_scope(kind, old, *about) if old is not None else None


def read(cache: JsonDiskCache, scope: str, keep_for: timedelta) -> Any | None:
    """What `cache` holds for `scope`, falling back once to its former spelling and refiling it.

    Only a scope with nothing at all under it falls back: one emptied since —
    every decision restored — is an answer, and must not bring the old ones back.
    """
    hit = cache.lookup(scope, keep_for)
    if hit is not None:
        return hit.value
    old = former(scope)
    if old is None or (found := cache.lookup(old, keep_for)) is None:
        return None
    cache.set(scope, found.value)
    return found.value
