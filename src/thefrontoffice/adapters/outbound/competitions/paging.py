"""Turning a ranked list of players into one window onto it.

Every sport builds its own ranking — a projection in football, expected points
in FPL, Yahoo's season rank in basketball — and then wants the same three
things done to it: keep the rows somebody asked for, order them by the column
they clicked (`PlayerOrder`, the rule every player table sorts by), and hand
back one page.

None of that is sport-specific, so none of it is written per sport. The one
thing a sport must supply is the number behind a formatted column, which it
does on the card: sorting "£15.5m" as text puts it below "£9.0m", and parsing
it back would mean teaching this module every sport's units.
"""

from collections.abc import Mapping, Sequence

from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import POSITION_COLUMN, PlayerCard, PlayerPage, PlayerQuery


def page(
    ranked: list[PlayerCard], query: PlayerQuery, filters: Mapping[str, frozenset[str]] | None = None
) -> PlayerPage:
    """Filter, order and window a list the sport has already ranked.

    The sport's own order is the default rather than a column sort, because
    that ranking is the answer to "who should I be looking at" and any column
    sort is a question about it.

    `filters` are the positions a sport offers, each with the eligibilities it
    keeps, for a sport whose players are eligible at several ('PG,SG'): a row
    is kept where any of his is among them. Without them, every position in the
    pool is offered, and a row is kept where his is the one asked for.
    """
    positions = (
        list(filters) if filters is not None else sorted({p.columns.get(POSITION_COLUMN, "") for p in ranked} - {""})
    )

    matched = [card for card in ranked if _matches(card, query, filters or {})]
    window = query.ordered(matched)[query.offset : query.offset + query.limit]
    return PlayerPage(players=window, total=len(matched), offset=query.offset, limit=query.limit, positions=positions)


def _matches(card: PlayerCard, query: PlayerQuery, filters: Mapping[str, frozenset[str]]) -> bool:
    if query.position and not _plays(card.columns.get(POSITION_COLUMN, ""), query.position, filters):
        return False
    if not query.search:
        return True
    # Across every column rather than the name alone: a search is as often for
    # a club or a status as for a person.
    return query.search.casefold() in " ".join(card.columns.values()).casefold()


def _plays(position: str, wanted: str, filters: Mapping[str, frozenset[str]]) -> bool:
    """Whether a row's `position` is kept by the filter `wanted`: any eligibility among its, or the same position."""
    kept = filters.get(wanted)
    if kept is None:
        return position == wanted
    return any(p.strip() in kept for p in position.split(","))


def view(query: PlayerQuery, offered: Sequence[str]) -> str:
    """Which of the `offered` lists `query` asks for, as offered; empty for the whole pool.

    Matched regardless of case, since a hand-typed `trending` means Sleeper's
    Trending as plainly as the button does. One nobody offers is refused rather
    than ignored: answering with the whole pool reads as that list.

    Raises:
        InvalidRequestError: a view that is not one of `offered`.
    """
    if not query.view:
        return ""
    wanted = query.view.casefold()
    found = next((name for name in offered if name.casefold() == wanted), None)
    if found is None:
        choices = f"one of {', '.join(offered)}" if offered else "none here"
        raise InvalidRequestError([f"No player list called {query.view!r}: {choices}."])
    return found
