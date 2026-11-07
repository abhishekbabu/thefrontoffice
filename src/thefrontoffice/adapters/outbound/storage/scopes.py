"""Scopes kept under a competition's former name, still found under its current one.

Kept answers and to-do decisions were once filed under a competition's
display label — `scout:NFL (Sleeper):<league>` — and are now filed under its
registry key, `scout:nfl-sleeper:<league>`. A store reading a scope it has
nothing under looks once more under the former name, and files what it finds
under the current one, so no kept judgment or dismissal is lost to the rename.
"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache


def former(scope: str, renamed: Mapping[str, str]) -> str | None:
    """`scope` as it was spelled before its competition was renamed; None where it never was.

    A scope is `kind:competition:...`, so the competition is its second part.
    """
    kind, sep, rest = scope.partition(":")
    competition, colon, about = rest.partition(":")
    old = renamed.get(competition) if sep else None
    return f"{kind}:{old}{colon}{about}" if old is not None else None


def read(cache: JsonDiskCache, scope: str, keep_for: timedelta, renamed: Mapping[str, str]) -> Any | None:
    """What `cache` holds for `scope`, falling back once to its former spelling and refiling it.

    Only a scope with nothing at all under it falls back: one emptied since —
    every decision restored — is an answer, and must not bring the old ones back.
    """
    stored = cache.get(scope, keep_for)
    old = former(scope, renamed) if stored is None else None
    if old is not None and (stored := cache.get(old, keep_for)) is not None:
        cache.set(scope, stored)
    return stored
