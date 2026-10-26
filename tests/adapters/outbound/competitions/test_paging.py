"""Tests for windowing a ranked player list.

One implementation serves every sport, so the rules it encodes are asserted
once here rather than three times over: the sport's ranking is the default,
a formatted column sorts on the number behind it, and a row with nothing to
sort on never displaces one that has something.
"""

from thefrontoffice.adapters.outbound.competitions.paging import page
from thefrontoffice.domain.models import PlayerCard, PlayerQuery


def _card(name: str, pos: str, price: float | None = None, club: str = "ARS") -> PlayerCard:
    return PlayerCard(
        player_id=name.lower(),
        columns={"Player": name, "Pos": pos, "Club": club, "Price": f"£{price:.1f}m" if price else ""},
        values={"Price": price} if price is not None else {},
    )


POOL = [
    _card("Haaland", "FWD", 15.5),
    _card("Saka", "MID", 9.5, club="ARS"),
    _card("Isak", "FWD", 9.0, club="NEW"),
    _card("Raya", "GKP", 5.5),
    _card("Nobody", "DEF"),  # no price at all
]


# ── the window ──────────────────────────────────────────────────────────


def test_a_page_reports_the_whole_size_not_the_window() -> None:
    """Otherwise there is no way to know there is a second page."""
    result = page(POOL, PlayerQuery(limit=2))

    assert [c.columns["Player"] for c in result.players] == ["Haaland", "Saka"]
    assert result.total == 5


def test_an_offset_moves_the_window() -> None:
    result = page(POOL, PlayerQuery(limit=2, offset=2))

    assert [c.columns["Player"] for c in result.players] == ["Isak", "Raya"]
    assert result.offset == 2


def test_an_offset_past_the_end_is_an_empty_page_not_an_error() -> None:
    result = page(POOL, PlayerQuery(offset=500))

    assert result.players == []
    assert result.total == 5


def test_the_positions_offered_come_from_the_whole_pool() -> None:
    """Not from the filtered rows, or choosing one would remove the others."""
    result = page(POOL, PlayerQuery(position="FWD"))

    assert result.positions == ["DEF", "FWD", "GKP", "MID"]


# ── ordering ────────────────────────────────────────────────────────────


def test_the_sports_own_ranking_is_the_default() -> None:
    """That ranking answers "who should I look at"; a column sort is a
    question about it, so it only applies when asked for."""
    result = page(POOL, PlayerQuery())

    assert [c.columns["Player"] for c in result.players][:2] == ["Haaland", "Saka"]


def test_a_formatted_column_sorts_on_the_number_behind_it() -> None:
    """Sorted as text, "£9.0m" sits above "£15.5m"."""
    result = page(POOL, PlayerQuery(sort="Price"))

    assert [c.columns["Price"] for c in result.players][:3] == ["£15.5m", "£9.5m", "£9.0m"]


def test_ascending_reverses_it() -> None:
    result = page(POOL, PlayerQuery(sort="Price", descending=False))

    assert result.players[0].columns["Player"] == "Raya"


def test_a_row_with_no_value_sorts_last_descending() -> None:
    assert page(POOL, PlayerQuery(sort="Price")).players[-1].columns["Player"] == "Nobody"


def test_a_row_with_no_value_sorts_last_ascending_too() -> None:
    """Folding "is it missing" into the sort key would bring the blanks to the
    top when reversed, where they push every real answer off the first page."""
    assert page(POOL, PlayerQuery(sort="Price", descending=False)).players[-1].columns["Player"] == "Nobody"


def test_a_column_with_no_numbers_sorts_as_text() -> None:
    result = page(POOL, PlayerQuery(sort="Player", descending=False))

    assert [c.columns["Player"] for c in result.players] == ["Haaland", "Isak", "Nobody", "Raya", "Saka"]


def test_sorting_by_a_column_nobody_has_leaves_the_order_alone() -> None:
    result = page(POOL, PlayerQuery(sort="Nonsense"))

    assert [c.columns["Player"] for c in result.players] == [c.columns["Player"] for c in POOL]


# ── filtering ───────────────────────────────────────────────────────────


def test_a_position_filter_keeps_only_that_position() -> None:
    result = page(POOL, PlayerQuery(position="FWD"))

    assert [c.columns["Player"] for c in result.players] == ["Haaland", "Isak"]
    assert result.total == 2


def test_search_looks_across_every_column_not_just_the_name() -> None:
    """A search is as often for a club or a status as for a person."""
    result = page(POOL, PlayerQuery(search="NEW"))

    assert [c.columns["Player"] for c in result.players] == ["Isak"]


def test_search_ignores_case() -> None:
    assert page(POOL, PlayerQuery(search="haaland")).total == 1


def test_filters_combine_rather_than_replace_each_other() -> None:
    assert page(POOL, PlayerQuery(position="FWD", search="NEW")).total == 1


def test_a_search_matching_nothing_is_an_empty_page() -> None:
    result = page(POOL, PlayerQuery(search="zzzz"))

    assert result.players == []
    assert result.total == 0
