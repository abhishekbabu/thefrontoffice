"""Tests for how a basketball player reads in a table row and in his drawer: `nba/views.py`.

Covered through the provider, which hands each view the player's recent run.
"""

from datetime import UTC, date, datetime

import pytest
from support.espn import FakeESPN
from support.nba import FakeNBA, FakeYahoo, make_player, nba_provider, toronto

from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog
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


def _form(played: int = 15, **stats: float) -> PlayerStats:
    """`played` identical games, run through the real nine-category line."""
    games = [NBAGameLog(player_id="p", date=f"2026-01-{i + 1:02d}", opponent="BOS", stats=stats) for i in range(played)]
    return PlayerStats(recent=RecentForm(games=played, line=nine_cat(games)))


def test_the_drawer_shows_every_category_of_the_last_fifteen() -> None:
    """The drawer once looked figures up in a way the form line never matched,
    and showed a dash where every figure should have been."""
    stats = _form(pts=20, reb=8, ast=5, stl=1, blk=2, tpm=3, to=2, fgm=9, fga=18, ftm=4, fta=5)
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])

    detail = nba_provider(yahoo, nba=FakeNBA(stats={"A B": stats})).player("", "ab")

    figures = {stat.label: stat.value for stat in detail.groups[0].stats}
    assert list(figures) == [c.label for c in CATEGORIES]
    assert figures == {
        "PTS": "20.0",
        "REB": "8.0",
        "AST": "5.0",
        "STL": "1.0",
        "BLK": "2.0",
        "3PTM": "3.0",
        "FG%": "50.0%",
        "FT%": "80.0%",
        "TO": "2.0",
    }
    assert detail.headline == "20.0"


def test_the_drawer_says_how_many_games_a_short_run_averages() -> None:
    """Twelve games in, the line is his last twelve, and saying fifteen would misstate it."""
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])

    detail = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(played=12, pts=18)})).player("", "ab")

    assert detail.headline == "18.0"
    assert "12" in detail.headline_label


def test_two_players_compare_with_fewer_turnovers_and_more_of_everything_else_best() -> None:
    """Runs of different lengths still line up on one grid: the run is in the headline, not the heading."""
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab"), make_player("C D", key="cd")])
    form = FakeNBA(
        stats={
            "A B": _form(pts=20, to=4, fgm=5, fga=10),
            "C D": _form(played=9, pts=12, to=1, fgm=6, fga=10),
        }
    )
    provider = nba_provider(yahoo, nba=form)

    [table] = comparison([provider.player("", "ab"), provider.player("", "cd")]).tables

    best = {row.label: row.best for row in table.rows}
    assert (best["PTS"], best["TO"], best["FG%"]) == ([0], [1], [1])


def test_a_row_short_of_fifteen_games_still_carries_figures() -> None:
    """Week five, most of a roster has fewer than fifteen games; a dash for each was the bug."""
    yahoo = FakeYahoo(roster=[make_player("A B")])

    card = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(played=7, pts=20)})).roster()[0]

    assert card.columns["PTS"] == "20.0"
    assert card.values["PTS"] == 20.0


def test_a_table_row_carries_recent_form() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=20, reb=8, ast=5)})).roster()[0]

    assert (card.columns["PTS"], card.columns["REB"], card.columns["AST"]) == ("20.0", "8.0", "5.0")


def test_recent_form_sorts_as_a_number() -> None:
    """Sorted as text, 9.0 points sits above 20.0."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=20, reb=8, ast=5)})).roster()[0]

    assert card.values == {"PTS": 20.0, "REB": 8.0, "AST": 5.0}


def test_the_drawer_opens_for_a_player_on_nobodys_roster_or_a_rivals() -> None:
    """The wire and other managers' rosters open the same drawer as your own."""
    yahoo = FakeYahoo(available=[make_player("Free Man", key="fa")])
    provider = nba_provider(yahoo)

    assert provider.player("", "fa").name == "Free Man"
    assert provider.player("", "their-team-one").name == "Their Team One"


def test_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider().player("", "nobody")


def test_a_percentage_with_nothing_attempted_is_a_dash_not_zero() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])
    detail = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=10)})).player("", "ab")

    figures = {stat.label: stat.value for stat in detail.groups[0].stats}
    assert (figures["FT%"], figures["PTS"]) == ("—", "10.0")


def test_recent_form_is_a_dash_when_there_is_none() -> None:
    """Out of season there is no line to show, and a zero would read as a bad
    one rather than an absent one."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
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
