"""Tests for players side by side: `application/comparing.py`."""

import pytest

from thefrontoffice.application.comparing import ABSENT, comparison
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import PlayerComparison, PlayerDetail, Stat, StatGroup, StatRow, StatTable


def _player(
    name: str, projected: str, owner: str = "", season: str = "", extra: list[Stat] | None = None
) -> PlayerDetail:
    return PlayerDetail(
        player_id=name.lower(),
        name=name,
        position="WR",
        team="DAL",
        owner=owner,
        rank="WR4",
        tabs=["This week", "News"],
        groups=[
            StatGroup(
                title="Week 11", stats=[Stat(label="Projected", value=projected, better="higher"), *(extra or [])]
            ),
            StatGroup(title="News", tab="News", stats=[Stat(label="Mon", value="Headline", url="https://x")]),
        ],
        tables=[
            StatTable(
                title="By season",
                tab="Seasons",
                columns=["2026", "2025"],
                rows=[
                    StatRow(label="Pts", values=[season, "1"], better="higher"),
                    StatRow(label="Position rank", values=[f"#{season}", "#1"], better="lower"),
                ],
            )
        ]
        if season
        else [],
    )


def _rows(compared: PlayerComparison, heading: str) -> dict[str, StatRow]:
    [table] = [t for t in compared.tables if t.title == heading]
    return {row.label: row for row in table.rows}


def test_each_heading_is_a_table_a_row_per_measure_and_a_column_per_player_in_the_order_asked() -> None:
    compared = comparison([_player("Lamb", "18.2", season="210"), _player("Nacua", "17.9", season="198")])

    assert [t.title for t in compared.tables] == ["Week 11", "2026 season"]
    assert all(t.columns == ["Lamb", "Nacua"] for t in compared.tables)
    assert _rows(compared, "Week 11")["Projected"].values == ["18.2", "17.9"]
    assert _rows(compared, "2026 season")["Pts"].values == ["210", "198"]


def test_owner_and_position_rank_are_left_to_the_header() -> None:
    compared = comparison([_player("Lamb", "18.2", owner="Rival"), _player("Nacua", "17.9")])

    labels = {row.label for table in compared.tables for row in table.rows}
    assert labels == {"Projected"}
    assert compared.players[0].owner == "Rival" and compared.players[0].rank == "WR4"


def test_a_figure_only_one_player_has_reads_as_absent_for_the_rest() -> None:
    compared = comparison([_player("A", "1", extra=[Stat(label="Injury", value="Knee")]), _player("B", "2")])

    assert _rows(compared, "Week 11")["Injury"].values == ["Knee", ABSENT]


def test_the_best_figure_is_marked_whichever_way_the_measure_improves() -> None:
    compared = comparison(
        [_player("A", "12.5", season="40"), _player("B", "18.2", season="12"), _player("C", "9", season="25")]
    )

    assert _rows(compared, "Week 11")["Projected"].best == [1]
    assert _rows(compared, "2026 season")["Position rank"].best == [1]


@pytest.mark.parametrize(
    ("values", "best"),
    [
        (["10", "10"], []),  # a tie says nothing
        (["10", "-"], []),  # one figure has nothing to beat
        (["82%", "95%", "95%"], [1, 2]),  # a shared best is marked on both
        (["1,204", "998"], [0]),
    ],
)
def test_only_figures_that_differ_are_marked(values: list[str], best: list[int]) -> None:
    players = [_player(f"P{i}", value) for i, value in enumerate(values)]

    assert _rows(comparison(players), "Week 11")["Projected"].best == best


def test_a_measure_that_does_not_say_which_way_is_better_is_not_marked() -> None:
    compared = comparison(
        [
            _player("A", "1", extra=[Stat(label="Depth chart", value="1")]),
            _player("B", "2", extra=[Stat(label="Depth chart", value="2")]),
        ]
    )

    assert _rows(compared, "Week 11")["Depth chart"].best == []


def test_headlines_are_not_compared_and_headers_carry_no_drawer() -> None:
    compared = comparison([_player("A", "1")])

    assert all(t.title != "News" for t in compared.tables)
    assert compared.players[0].groups == [] and compared.players[0].tables == []


@pytest.mark.parametrize("count", [0, 5])
def test_one_to_four_players_compare(count: int) -> None:
    with pytest.raises(InvalidRequestError):
        comparison([_player(f"P{i}", "1") for i in range(count)])
