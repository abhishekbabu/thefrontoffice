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

from thefrontoffice.domain.models import POSITION_COLUMN, PlayerCard, PlayerPage, PlayerQuery


def page(ranked: list[PlayerCard], query: PlayerQuery) -> PlayerPage:
    """Filter, order and window a list the sport has already ranked.

    The sport's own order is the default rather than a column sort, because
    that ranking is the answer to "who should I be looking at" and any column
    sort is a question about it.
    """
    positions = sorted({p.columns.get(POSITION_COLUMN, "") for p in ranked} - {""})

    matched = [card for card in ranked if _matches(card, query)]
    window = query.ordered(matched)[query.offset : query.offset + query.limit]
    return PlayerPage(players=window, total=len(matched), offset=query.offset, limit=query.limit, positions=positions)


def _matches(card: PlayerCard, query: PlayerQuery) -> bool:
    if query.position and card.columns.get(POSITION_COLUMN) != query.position:
        return False
    if not query.search:
        return True
    # Across every column rather than the name alone: a search is as often for
    # a club or a status as for a person.
    return query.search.casefold() in " ".join(card.columns.values()).casefold()
