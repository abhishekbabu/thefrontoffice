"""Tests for the latest injury report, joined to Sleeper: `nfl/injuries.py`."""

from datetime import UTC, datetime

from support.nfl import proj

from thefrontoffice.adapters.outbound.competitions.nfl.injuries import catalog, designations, reported
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta

PLAYERS = {
    "hall": PlayerMeta(player_id="hall", name="Breece Hall", position="RB", team="NYJ", injury_status="Out"),
    "wash": PlayerMeta(player_id="wash", name="Antonio Williams", position="WR", team="WAS"),
    "kc1": PlayerMeta(player_id="kc1", name="Chris Jones", position="WR", team="KC"),
    "kc2": PlayerMeta(player_id="kc2", name="Chris Jones", position="TE", team="KC"),
}


def _report(name: str, club: str, status: str) -> InjuryReport:
    return InjuryReport(name=name, club=club, status=status, updated=datetime(2026, 10, 27, 13, tzinfo=UTC))


def test_the_report_names_a_player_by_his_name_on_his_own_club() -> None:
    assert designations([_report("Breece Hall", "NYJ", "Questionable")], PLAYERS) == {"hall": "Questionable"}


def test_a_club_is_read_in_espns_spelling() -> None:
    assert designations([_report("Antonio Williams", "WSH", "Out")], PLAYERS) == {"wash": "Out"}


def test_a_player_of_the_same_name_on_another_club_is_not_him() -> None:
    assert designations([_report("Breece Hall", "BUF", "Out")], PLAYERS) == {}


def test_a_name_two_players_on_a_club_share_is_nobodys() -> None:
    assert designations([_report("Chris Jones", "KC", "Out")], PLAYERS) == {}


def test_a_player_cleared_to_play_carries_no_designation() -> None:
    assert designations([_report("Breece Hall", "NYJ", "Active")], PLAYERS) == {"hall": ""}


def test_a_designation_the_rules_have_no_word_for_changes_nothing() -> None:
    assert designations([_report("Breece Hall", "NYJ", "Day-To-Day")], PLAYERS) == {}


def test_a_long_ruling_reads_in_sleepers_words() -> None:
    assert designations([_report("Breece Hall", "NYJ", "Injured Reserve")], PLAYERS) == {"hall": "IR"}


def test_a_projection_takes_the_reports_designation_and_keeps_his_points() -> None:
    projection = proj("hall", "Breece Hall", "RB", 11.2, team="NYJ", opp="LV")

    [after] = reported({"hall": projection}, {"hall": "Questionable"}).values()

    assert (after.injury_status, after.points, after.opponent) == ("Questionable", 11.2, "LV")


def test_a_projection_the_report_does_not_name_is_left_as_published() -> None:
    projection = proj("wash", "Antonio Williams", "WR", 7.1, team="WAS")

    assert reported({"wash": projection}, {"hall": "Out"})["wash"] is projection


def test_the_catalog_takes_the_reports_designation_without_changing_sleepers() -> None:
    updated = catalog(PLAYERS, {"hall": "Questionable"})

    assert updated["hall"].get("injury_status") == "Questionable"
    assert PLAYERS["hall"].get("injury_status") == "Out"
