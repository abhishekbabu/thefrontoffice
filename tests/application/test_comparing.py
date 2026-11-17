"""Tests for players side by side: `application/comparing.py`."""

import pytest

from thefrontoffice.application.comparing import ABSENT, comparison
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import PlayerDetail, Stat, StatGroup, StatRow, StatTable


def _player(
    name: str, projected: str, owner: str = "", season: str = "", extra: list[Stat] | None = None
) -> PlayerDetail:
    return PlayerDetail(
        player_id=name.lower(),
        name=name,
        position="WR",
        team="DAL",
        owner=owner,
        tabs=["This week", "News"],
        groups=[
            StatGroup(title="Week 11", stats=[Stat(label="Projected", value=projected), *(extra or [])]),
            StatGroup(title="News", tab="News", stats=[Stat(label="Mon", value="Headline", url="https://x")]),
        ],
        tables=[
            StatTable(
                title="By season",
                tab="Seasons",
                columns=["2026", "2025"],
                rows=[StatRow(label="Pts", values=[season, "1"])],
            )
        ]
        if season
        else [],
    )


def test_each_measure_is_a_row_and_each_player_a_column_in_the_order_asked() -> None:
    compared = comparison(
        [_player("Lamb", "18.2", owner="Rival", season="210"), _player("Nacua", "17.9", season="198")]
    )

    assert compared.table.columns == ["Lamb", "Nacua"]
    rows = {row.label: row.values for row in compared.table.rows}
    assert rows["Week 11 · Projected"] == ["18.2", "17.9"]
    assert rows["2026 · Pts"] == ["210", "198"]
    assert rows["Owner"] == ["Rival", ABSENT]


def test_a_figure_only_one_player_has_reads_as_absent_for_the_rest() -> None:
    compared = comparison([_player("A", "1", extra=[Stat(label="Injury", value="Knee")]), _player("B", "2")])

    assert {row.label: row.values for row in compared.table.rows}["Week 11 · Injury"] == ["Knee", ABSENT]


def test_headlines_are_not_compared_and_headers_carry_no_drawer() -> None:
    compared = comparison([_player("A", "1")])

    assert all("News" not in row.label for row in compared.table.rows)
    assert compared.players[0].groups == [] and compared.players[0].tables == []


@pytest.mark.parametrize("count", [0, 5])
def test_one_to_four_players_compare(count: int) -> None:
    with pytest.raises(InvalidRequestError):
        comparison([_player(f"P{i}", "1") for i in range(count)])
