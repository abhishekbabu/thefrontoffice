"""Tests for how a basketball player reads in a table row and in his drawer: `nba/views.py`.

Covered through the provider, which hands each view Yahoo's averages for the player.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from support.espn import FakeESPN
from support.nba import FakeNBA, FakeYahoo, make_player, nba_provider, toronto

from thefrontoffice.adapters.outbound.competitions.nba.rules import ASSISTS, BLOCKS, CATEGORIES, POINTS, REBOUNDS
from thefrontoffice.adapters.outbound.competitions.nba.views import cell, compared
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Average, YahooLine, YahooPlayer
from thefrontoffice.application.comparing import comparison
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import PlayerQuery


def test_a_roster_card_carries_the_row_and_what_a_row_cannot() -> None:
    """The columns are the table; the id and the tone are what a table needs
    and a column should not be."""
    yahoo = FakeYahoo(roster=[make_player("A B", "PF,C", "LAL", status="O", selected_position="IL")])

    card = nba_provider(yahoo).roster()[0]

    assert card.columns["Player"] == "A B"
    assert card.columns["Slot"] == "IL"
    assert card.player_id
    assert card.ruled_out


def test_a_game_time_decision_is_flagged_without_being_ruled_out() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", status="GTD")])

    card = nba_provider(yahoo).roster()[0]

    assert (card.columns["Status"], card.ruled_out) == ("GTD", False)


SEASON_LINE = YahooLine(
    stats={
        "12": "15.7",
        "15": "7.1",
        "16": "3.3",
        "17": "1.1",
        "18": "0.7",
        "10": "0.3",
        "5": "0.536",
        "8": "1.0",
        "19": "1.9",
    }
)
MONTH_LINE = YahooLine(stats={"12": "17.7", "15": "8.7", "16": "4.0", "5": "0.51", "8": "-", "19": "2.3"})


def _averaged(*players: YahooPlayer, season: YahooLine = SEASON_LINE, month: YahooLine = MONTH_LINE) -> FakeYahoo:
    """`players` on your roster, each with these averages over the season and the last month."""
    yahoo = FakeYahoo(roster=list(players))
    yahoo.lines = {
        Average.SEASON: {p.player_key: season for p in players},
        Average.LAST_MONTH: {p.player_key: month for p in players},
    }
    return yahoo


def test_the_drawer_shows_yahoos_season_and_last_month_in_every_category_the_league_scores() -> None:
    yahoo = _averaged(make_player("A B", key="ab"))

    detail = nba_provider(yahoo).player("", "ab")

    season, month = ({s.label: s.value for s in g.stats} for g in detail.groups[:2])
    assert [g.title for g in detail.groups[:2]] == ["Season", "Last 30 days"]
    assert list(season) == [c.label for c in CATEGORIES]
    assert (season["PTS"], season["FG%"], season["FT%"], season["TO"]) == ("15.7", ".536", "1.000", "1.9")
    assert (month["PTS"], month["FT%"], month["STL"]) == ("17.7", "—", "—")
    assert (detail.headline, detail.headline_label) == ("15.7", "pts/game, season")
    assert yahoo.averaged == [(("ab",), (Average.SEASON, Average.LAST_MONTH))]


def test_a_drawer_yahoo_has_no_averages_for_says_so_and_still_opens() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])
    yahoo.averages_error = YahooAPIError("down")

    detail = nba_provider(yahoo).player("", "ab")

    assert (detail.headline, detail.headline_label) == ("", "No games this season")
    assert {"Season", "Last 30 days"}.isdisjoint(g.title for g in detail.groups)


def test_two_players_compare_with_fewer_turnovers_and_more_of_everything_else_best() -> None:
    yahoo = _averaged(make_player("A B", key="ab"))
    yahoo.roster_players.append(make_player("C D", key="cd"))
    yahoo.lines[Average.SEASON]["cd"] = YahooLine(stats={"12": "12.0", "19": "1.0", "5": ".600"})
    provider = nba_provider(yahoo)

    [season, *_] = comparison([provider.player("", "ab"), provider.player("", "cd")]).tables

    best = {row.label: row.best for row in season.rows}
    assert (best["PTS"], best["TO"], best["FG%"]) == ([0], [1], [1])


def test_a_table_row_carries_yahoos_last_month_as_printed_and_sorts_on_its_numbers() -> None:
    """Sorted as text, 9.0 points sits above 20.0."""
    card = nba_provider(_averaged(make_player("A B"))).roster()[0]

    assert (card.columns["PTS"], card.columns["REB"], card.columns["AST"]) == ("17.7", "8.7", "4.0")
    assert card.values == {"PTS": 17.7, "REB": 8.7, "AST": 4.0}


def test_a_rivals_roster_carries_his_players_averages_too() -> None:
    yahoo = FakeYahoo()
    yahoo.lines = {Average.LAST_MONTH: {"their-team-one": MONTH_LINE}}

    [card] = nba_provider(yahoo).roster_of("", "t.2")

    assert card.columns["PTS"] == "17.7"


def test_the_wire_reads_the_averages_its_own_pages_carry_without_another_request() -> None:
    carried = make_player("Free Man", key="fa", stats={"12": "9.5"}, coverage=Average.LAST_MONTH)
    yahoo = FakeYahoo(available=[carried])

    [card] = nba_provider(yahoo).free_agents("", PlayerQuery()).players

    assert card.columns["PTS"] == "9.5"
    assert yahoo.averaged == []


def test_the_drawer_opens_for_a_player_on_nobodys_roster_or_a_rivals() -> None:
    """The wire and other managers' rosters open the same drawer as your own."""
    yahoo = FakeYahoo(available=[make_player("Free Man", key="fa")])
    provider = nba_provider(yahoo)

    assert provider.player("", "fa").name == "Free Man"
    assert provider.player("", "their-team-one").name == "Their Team One"


def test_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider().player("", "nobody")


def test_an_average_is_a_dash_when_there_is_none() -> None:
    """Out of season there is no line to show, and a zero would read as a bad
    one rather than an absent one."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    yahoo.averages_error = YahooAPIError("down")
    card = nba_provider(yahoo).roster()[0]

    assert card.columns["PTS"] == "—"
    assert "PTS" not in card.values


# ── teammates out ───────────────────────────────────────────────────────

POELTL = make_player("Jakob Poeltl", "C", "TOR", key="poeltl")
BARNES_OUT = [
    InjuryReport(
        name="Scottie Barnes",
        club="TOR",
        status="Out",
        updated=datetime(2026, 11, 18, tzinfo=UTC),
        returns=date(2026, 11, 22),
    )
]


def test_the_wire_shows_whose_absence_a_free_agent_gains_from_with_both_figures_on_hover() -> None:
    yahoo = FakeYahoo(available=[POELTL, make_player("Somebody Else", key="else")])
    provider = nba_provider(yahoo, nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT))

    poeltl, other = provider.free_agents("", PlayerQuery()).players

    assert poeltl.columns[WITHOUT_COLUMN] == "Barnes O"
    assert poeltl.notes[WITHOUT_COLUMN].startswith("Without Scottie Barnes")
    assert "12.0" in poeltl.notes[WITHOUT_COLUMN]
    assert other.columns[WITHOUT_COLUMN] == "—"
    assert WITHOUT_COLUMN not in other.notes


def test_a_roster_has_no_without_column() -> None:
    provider = nba_provider(
        FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT)
    )

    assert WITHOUT_COLUMN not in provider.roster()[0].columns


def test_the_drawer_lists_his_line_without_each_teammate_out() -> None:
    provider = nba_provider(
        FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT)
    )

    [group] = [g for g in provider.player("", "poeltl").groups if g.title == "Teammates"]

    [row] = group.stats
    assert row.label.startswith("Without Scottie Barnes")
    assert row.tone == "good"


def test_a_teammate_who_lately_sat_counts_when_espns_report_will_not_load() -> None:
    espn = FakeESPN(injuries_error=ESPNAPIError("down"))
    provider = nba_provider(FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=espn)

    [group] = [g for g in provider.player("", "poeltl").groups if g.title == "Teammates"]

    assert group.stats[0].label.startswith("With Scottie Barnes")


def test_a_drawer_with_no_teammate_out_has_no_teammates_group() -> None:
    provider = nba_provider(FakeYahoo(roster=[make_player("A B", key="ab")]), nba=FakeNBA(scores=toronto()))

    assert "Teammates" not in [g.title for g in provider.player("", "ab").groups]


READING = Reading(
    player=make_player("A B"),
    line={POINTS.label: 22.1, REBOUNDS.label: 8.3, ASSISTS.label: 4.0, BLOCKS.label: 1.0},
    per_game=41.5,
    games=3,
)


def test_a_points_league_row_reads_games_left_and_fantasy_points_a_game() -> None:
    assert cell(READING, by_points=True) == "3G · 41.5 fpts/g"


def test_a_category_league_row_reads_games_left_and_the_line_a_row_has_room_for() -> None:
    assert cell(READING, by_points=False) == "3G · 22.1p 8.3r 4.0a"


def test_a_row_without_a_schedule_reads_the_game_alone() -> None:
    assert cell(replace(READING, games=None), by_points=True) == "41.5 fpts/g"


def test_players_compared_carry_the_same_rows_with_a_dash_where_one_has_none() -> None:
    known, unknown = replace(READING, minutes=30.0), replace(READING, per_game=None, games=None)

    rows = [
        [(f.label, f.value) for f in p.figures]
        for p in compared([("in", "bench", known), ("out", "starter", unknown)], True)
    ]

    assert [label for label, _ in rows[0]] == [label for label, _ in rows[1]]
    assert dict(rows[0])["Week"] == "124.5"
    assert dict(rows[1])["Week"] == "—"


def test_games_left_read_as_a_floor_while_the_weeks_schedule_is_not_final() -> None:
    pending = replace(READING, provisional=True)

    assert cell(pending, by_points=True) == "3+G · 41.5 fpts/g"
    [_in] = compared([("in", "bench", pending)], True)
    assert {f.label: f.value for f in _in.figures}["G left"] == "3+"
