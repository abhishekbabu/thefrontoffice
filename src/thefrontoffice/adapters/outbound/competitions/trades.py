"""Resolving the players named in a trade, and what one side could offer for a player.

How a name becomes a player differs per platform — a Yahoo search, a lookup
against a Sleeper catalog — but the policy around it does not: resolve both
sides, and if anything failed, name every failure at once. A user with a typo on
each side should fix one message, not discover the second on the re-run.

How a player is priced differs per competition too, but what is offered for him
does not (`offers`): one player worth near enough what is asked, or two where
neither is.
"""

from collections.abc import Callable, Sequence
from itertools import combinations

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


FAIR_SHARE = 0.8
"""The least of what they give, in worth, that they must get back: a gap a better lineup can talk a manager
into, and no wider."""


def offers(mine: Sequence[str], worth: Callable[[str], float], asked: float) -> list[tuple[str, ...]]:
    """What you could give for a player worth `asked`: one who is enough alone, or two where neither is.

    Two where one would do is a player thrown away, so a pair is offered only
    when it takes both to come near what is asked.
    """
    enough = FAIR_SHARE * asked
    alone: list[tuple[str, ...]] = [(pid,) for pid in mine if worth(pid) >= enough]
    short = [pid for pid in mine if 0 < worth(pid) < enough]
    pairs: list[tuple[str, ...]] = [p for p in combinations(short, 2) if worth(p[0]) + worth(p[1]) >= enough]
    return alone + pairs
