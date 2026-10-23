"""Matching player names across platforms.

Fantasy platforms and stats providers rarely share an identifier, so a player
typed by a user or listed by one service has to be matched to another by name.
The policy is deliberately conservative: a wrong match silently attributes one
player's numbers to another, which is worse than no match at all.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Reduce a name to a comparable key.

    Strips accents, punctuation and generational suffixes, so "Luka Dončić",
    "Luka Doncic" and "Jaren Jackson Jr." all match across platforms.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    # A hyphen separates words, an apostrophe does not: "Karl-Anthony" becomes
    # "karl anthony", "De'Aaron" becomes "deaaron".
    spaced = ascii_only.lower().replace("-", " ").replace(".", " ")
    cleaned = re.sub(r"[^a-z ]", "", spaced)
    parts = [p for p in cleaned.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


class NameIndex[T]:
    """Values looked up by player name, refusing ambiguity.

    An exact normalized match wins. Failing that, a surname match is allowed
    only when that surname is unique in the index — two Jacksons resolve to
    neither rather than to whichever was added first.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, T] = {}
        self._by_surname: dict[str, str] = {}
        self._ambiguous: set[str] = set()

    def add(self, name: str, value: T) -> None:
        key = normalize_name(name)
        if not key:
            return
        self._by_name[key] = value

        surname = key.rsplit(" ", 1)[-1]
        existing = self._by_surname.get(surname)
        if existing is None and surname not in self._ambiguous:
            self._by_surname[surname] = key
        elif existing is not None and existing != key:
            del self._by_surname[surname]
            self._ambiguous.add(surname)

    def lookup(self, name: str) -> T | None:
        """The value for `name`, or None if it cannot be matched unambiguously."""
        key = normalize_name(name)
        if not key:
            return None
        if key in self._by_name:
            return self._by_name[key]

        surname = key.rsplit(" ", 1)[-1]
        if surname in self._ambiguous:
            logger.debug(f"Ambiguous surname for {name!r}; no match applied")
            return None
        matched = self._by_surname.get(surname)
        return self._by_name.get(matched) if matched else None

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def is_empty(self) -> bool:
        return not self._by_name
