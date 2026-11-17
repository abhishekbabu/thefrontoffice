"""Players side by side, from what each one's drawer already shows.

Any competition that answers `player` can be compared without a line of its
own: the figures in each drawer's first tab, and this season out of its
by-season table, laid on one grid. A figure only some of them have reads as
absent for the rest rather than as nought.
"""

from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import (
    MAX_COMPARED,
    PlayerComparison,
    PlayerDetail,
    StatRow,
    StatTable,
)

ABSENT = "—"
"""A cell for a measure a player has no figure for."""

OWNER = "Owner"
RANK = "Position rank"


def comparison(details: list[PlayerDetail]) -> PlayerComparison:
    """`details` on one grid: a row per measure any of them has, a column per player, in the order given.

    Raises:
        InvalidRequestError: more than `MAX_COMPARED` players, or none.
    """
    if not 1 <= len(details) <= MAX_COMPARED:
        raise InvalidRequestError([f"Compare 1 to {MAX_COMPARED} players."])
    lines = [_figures(detail) for detail in details]
    measures = list(dict.fromkeys(label for figures in lines for label in figures))
    rows = [StatRow(label=label, values=[figures.get(label, ABSENT) for figures in lines]) for label in measures]
    return PlayerComparison(
        players=[detail.model_copy(update={"groups": [], "tables": [], "tabs": []}) for detail in details],
        table=StatTable(title="Compared", columns=[detail.name for detail in details], rows=rows, absent=ABSENT),
    )


def _figures(detail: PlayerDetail) -> dict[str, str]:
    """One player's comparable figures by measure: owner, his first tab's groups, and this season.

    Headlines are left out, being articles rather than figures, as are later
    tabs: a game log and a history are his alone, with nothing to line up.
    """
    first = detail.tabs[0] if detail.tabs else ""
    figures: dict[str, str] = {OWNER: detail.owner} if detail.owner else {}
    if detail.rank:
        figures[RANK] = detail.rank
    for group in detail.groups:
        if (group.tab or first) != first:
            continue
        for stat in group.stats:
            if not stat.url:
                figures[f"{group.title} · {stat.label}"] = stat.value
    for table in detail.tables:
        if table.title.lower().startswith("by season") and table.columns:
            for row in table.rows:
                if row.values:
                    figures[f"{table.columns[0]} · {row.label}"] = row.values[0]
    return figures
