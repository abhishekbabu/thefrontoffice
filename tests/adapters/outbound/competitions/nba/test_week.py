"""Tests for a category league's week as the page reads it: `nba/week.py`."""

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba import week
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, FIELD_GOALS, POINTS, TURNOVERS
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory

NINE = [
    StatCategory(c.yahoo_stat, c.label, fewer_wins=c is TURNOVERS) for c in (POINTS, BLOCKS, FIELD_GOALS, TURNOVERS)
]


def test_each_category_is_led_by_the_side_with_more_of_it() -> None:
    lines = week.categories(
        NINE,
        {POINTS.yahoo_stat: "520", BLOCKS.yahoo_stat: "12", FIELD_GOALS.yahoo_stat: ".482"},
        {POINTS.yahoo_stat: "498", BLOCKS.yahoo_stat: "17", FIELD_GOALS.yahoo_stat: ".482"},
    )

    assert [(line.name, line.lead) for line in lines] == [
        ("PTS", "mine"),
        ("BLK", "theirs"),
        ("FG%", "even"),
        ("TO", None),  # scored, but nothing recorded in it
    ]


def test_fewer_turnovers_wins_turnovers() -> None:
    [line] = week.categories(NINE[3:], {TURNOVERS.yahoo_stat: "40"}, {TURNOVERS.yahoo_stat: "52"})

    assert line.lead == "mine"


def test_a_week_with_nothing_recorded_has_no_leader_and_no_score() -> None:
    """A week to come prints a dash where a figure will be: nobody leads it, nor is it 0-0-9."""
    lines = week.categories([NINE[0]], {POINTS.yahoo_stat: "-"}, {POINTS.yahoo_stat: "-"})

    assert [line.lead for line in lines] == [None]
    assert week.score(lines) is None


def test_the_score_counts_categories_won_lost_and_level() -> None:
    lines = week.categories(
        NINE,
        {POINTS.yahoo_stat: "520", BLOCKS.yahoo_stat: "12", TURNOVERS.yahoo_stat: "40"},
        {POINTS.yahoo_stat: "498", BLOCKS.yahoo_stat: "17", TURNOVERS.yahoo_stat: "40"},
    )
    score = week.score(lines)

    assert score == (1, 1, 1)
    assert week.headline((5, 3, 1)).tone == "good"
    assert week.headline((3, 5, 1)).tone == "warning"


def test_a_roster_is_parted_as_yahoo_slots_it() -> None:
    roster = [
        make_player("Starter", selected_position="PG"),
        make_player("Sitter", selected_position="BN"),
        make_player("Hurt", selected_position="IL", status="INJ"),
    ]
    side = week.side("Mine", "4-2", "5-3-1", roster)

    assert [(s.slot, s.player) for s in side.lineup] == [("PG", "Starter")]
    assert [(s.slot, s.player) for s in side.bench] == [("", "Sitter")]
    assert [(s.slot, s.player, s.tone) for s in side.reserve] == [("", "Hurt", "neutral")]


def test_a_starter_ruled_out_warns_on_his_row() -> None:
    [row] = week.side("Mine", "", "", [make_player("Out", selected_position="C", status="O")]).lineup

    assert row.tone == "warning"


def test_a_week_with_no_roster_to_show_has_no_rows() -> None:
    side = week.side("Mine", "4-2", "5-3-1", None)

    assert (side.lineup, side.bench, side.reserve) == ([], [], [])


def test_the_board_reads_whatever_categories_the_league_scores() -> None:
    """A league scoring double-doubles shows them; one that does not score free throws shows none."""
    scored = [StatCategory("27", "DD"), StatCategory(POINTS.yahoo_stat, "PTS")]
    lines = week.categories(scored, {"27": "4", POINTS.yahoo_stat: "500"}, {"27": "6", POINTS.yahoo_stat: "480"})

    assert [(line.name, line.lead) for line in lines] == [("DD", "theirs"), ("PTS", "mine")]
