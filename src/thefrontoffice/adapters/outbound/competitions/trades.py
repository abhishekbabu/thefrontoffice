"""Resolving the players named in a trade.

How a name becomes a player differs per platform — a Yahoo search, a lookup
against a Sleeper catalog — but the policy around it does not: resolve both
sides, and if anything failed, name every failure at once. A user with a typo on
each side should fix one message, not discover the second on the re-run.
"""

from collections.abc import Callable

from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import TradeProposal


def resolve_sides[T](proposal: TradeProposal, resolve_one: Callable[[str], T | None]) -> tuple[list[T], list[T]]:
    """Resolve both sides of a trade.

    Args:
        resolve_one: turns a single name into a player, or None if it cannot.

    Raises:
        PlayerNotFoundError: naming every unresolved player. Silently dropping
            one would evaluate a different trade than the user described.
    """
    sides: list[list[T]] = []
    unresolved: list[str] = []

    for names in (proposal.giving, proposal.receiving):
        resolved: list[T] = []
        for name in names:
            clean = name.strip()
            match = resolve_one(clean)
            if match is None:
                unresolved.append(clean)
            else:
                resolved.append(match)
        sides.append(resolved)

    if unresolved:
        raise PlayerNotFoundError(unresolved)
    return sides[0], sides[1]
