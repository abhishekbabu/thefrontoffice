"""Players side by side, from what each one's drawer already shows.

Any competition that answers `player` can be compared without a line of its
own: the figures in each drawer's first tab, and this season out of its
by-season table, laid on one grid per heading. A figure only some of them have
reads as absent for the rest rather than as nought, and the best of a measure
that says which way it improves is marked.

Owner and position rank are left to the header, which carries both already.
"""

import re

from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import (
    MAX_COMPARED,
    Better,
    PlayerComparison,
    PlayerDetail,
    StatRow,
    StatTable,
)

ABSENT = "—"
"""A cell for a measure a player has no figure for."""

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

Figure = tuple[str, Better | None]
"""A value as shown, and which way it improves."""


def comparison(details: list[PlayerDetail]) -> PlayerComparison:
    """`details` on one grid per heading: a row per measure any of them has, a column per player, in the order given.

    Raises:
        InvalidRequestError: more than `MAX_COMPARED` players, or none.
    """
    if not 1 <= len(details) <= MAX_COMPARED:
        raise InvalidRequestError([f"Compare 1 to {MAX_COMPARED} players."])
    lines = [_figures(detail) for detail in details]
    headings = list(dict.fromkeys(heading for figures in lines for heading in figures))
    names = [detail.name for detail in details]
    tables = []
    for heading in headings:
        sections = [figures.get(heading, {}) for figures in lines]
        measures = list(dict.fromkeys(label for section in sections for label in section))
        rows = [_row(label, [section.get(label) for section in sections]) for label in measures]
        tables.append(StatTable(title=heading, columns=names, rows=rows, absent=ABSENT))
    return PlayerComparison(
        players=[detail.model_copy(update={"groups": [], "tables": [], "tabs": []}) for detail in details],
        tables=tables,
    )


def _row(label: str, cells: list[Figure | None]) -> StatRow:
    """One measure across the players, its best cells marked where the measure says which way is better."""
    better = next((figure[1] for figure in cells if figure and figure[1]), None)
    values = [figure[0] if figure else ABSENT for figure in cells]
    return StatRow(label=label, values=values, better=better, best=_best(values, better))


def _best(values: list[str], better: Better | None) -> list[int]:
    """Indexes of the best figures; none where fewer than two compare, or all of them tie."""
    if better is None:
        return []
    numbers = {i: n for i, value in enumerate(values) if (n := _number(value)) is not None}
    if len(numbers) < 2 or len(set(numbers.values())) == 1:
        return []
    top = max(numbers.values()) if better == "higher" else min(numbers.values())
    return [i for i, n in numbers.items() if n == top]


def _number(value: str) -> float | None:
    """The figure a cell leads with — '82%' is 82, '#12' is 12, '£14.0m' is 14 — or None for prose."""
    match = _NUMBER.search(value.replace(",", ""))
    return float(match.group()) if match else None


def _figures(detail: PlayerDetail) -> dict[str, dict[str, Figure]]:
    """One player's comparable figures, by heading and then measure: his first tab's groups, and this season.

    Headlines are left out, being articles rather than figures, as are later
    tabs: a game log and a history are his alone, with nothing to line up.
    """
    first = detail.tabs[0] if detail.tabs else ""
    figures: dict[str, dict[str, Figure]] = {}
    for group in detail.groups:
        if (group.tab or first) != first:
            continue
        for stat in group.stats:
            if not stat.url:
                figures.setdefault(group.title, {})[stat.label] = (stat.value, stat.better)
    for table in detail.tables:
        if table.title.lower().startswith("by season") and table.columns:
            for row in table.rows:
                if row.values:
                    figures.setdefault(f"{table.columns[0]} season", {})[row.label] = (row.values[0], row.better)
    return figures
