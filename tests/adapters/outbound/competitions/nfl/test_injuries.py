"""Tests for the latest injury report, joined to Sleeper: `nfl/injuries.py`.

The name and id join, and how an injury reads in the drawer, are shared, and covered in
`competitions/test_injuries.py`; these cover football's clubs, designations, lookups and return weeks.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from support.nfl import SEASON_SCHEDULE, proj

from thefrontoffice.adapters.outbound.competitions.nfl.injuries import (
    athletes,
    catalog,
    designations,
    long_return,
    matched,
    reported,
    return_week,
    short_return,
    unreported,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import Athlete, InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta

PLAYERS = {
    "hall": PlayerMeta(player_id="hall", name="Breece Hall", position="RB", team="NYJ", injury_status="Out"),
    "wash": PlayerMeta(player_id="wash", name="Antonio Williams", position="WR", team="WAS"),
}


SCHEDULE = {w: [g for g in SEASON_SCHEDULE if g.week == w] for w in {g.week for g in SEASON_SCHEDULE}}


def _report(name: str, club: str, status: str) -> InjuryReport:
    return InjuryReport(name=name, club=club, status=status, updated=datetime(2026, 10, 27, 13, tzinfo=UTC))


def _designations(reports: Sequence[InjuryReport]) -> dict[str, str]:
    return designations(matched(reports, PLAYERS, {}))


@pytest.mark.parametrize(
    ("espn", "sleeper"), [("Questionable", "Questionable"), ("Injured Reserve", "IR"), ("Active", "")]
)
def test_the_report_names_a_player_on_his_club_in_sleepers_words_and_cleared_as_none(espn: str, sleeper: str) -> None:
    assert _designations([_report("Breece Hall", "NYJ", espn)]) == {"hall": sleeper}


def test_a_designation_the_rules_have_no_word_for_changes_nothing() -> None:
    assert _designations([_report("Breece Hall", "NYJ", "Day-To-Day")]) == {}


def test_a_club_is_read_in_espns_spelling() -> None:
    assert _designations([_report("Antonio Williams", "WSH", "Out")]) == {"wash": "Out"}


RULED_OUT = {
    "out": PlayerMeta(player_id="out", name="Out Man", position="WR", team="WAS", injury_status="Out"),
    "ir": PlayerMeta(player_id="ir", name="Ir Man", position="RB", team="NYJ", injury_status="IR", espn_id="5"),
    "q": PlayerMeta(player_id="q", name="Q Man", position="TE", team="NYJ", injury_status="Questionable"),
    "fa": PlayerMeta(player_id="fa", name="Free Man", position="RB", team="FA", injury_status="IR"),
    "def": PlayerMeta(player_id="def", name="Jets", position="DEF", team="NYJ", injury_status="Out"),
    "k": PlayerMeta(player_id="k", name="Kick Man", position="K", team="NYJ", injury_status="IR"),
}


def test_only_players_ruled_out_on_a_club_and_missing_from_the_report_are_asked_after() -> None:
    found = {"k": _report("Kick Man", "NYJ", "Active")}

    assert unreported(RULED_OUT, found) == ["ir", "out"]


def _athletes(roster: list[Athlete], espn_ids: dict[str, str] | None = None) -> dict[str, str]:
    found = athletes(["out", "ir"], RULED_OUT, espn_ids if espn_ids is not None else {"5": "ir"}, roster)
    return {pid: a.athlete_id for pid, a in found.items()}


def test_sleepers_espn_id_is_used_as_it_stands_and_a_name_is_found_on_his_clubs_roster() -> None:
    roster = [Athlete(athlete_id="9", name="Out Man", club="WSH"), Athlete(athlete_id="6", name="Ir Man", club="NYJ")]

    assert _athletes(roster) == {"ir": "5", "out": "9"}


def test_a_name_on_another_club_or_shared_by_two_on_his_finds_nobody() -> None:
    elsewhere = [Athlete(athlete_id="9", name="Out Man", club="NYJ")]
    shared = [Athlete(athlete_id="9", name="Out Man", club="WSH"), Athlete(athlete_id="8", name="Out Man", club="WSH")]

    assert _athletes(elsewhere) == {"ir": "5"}
    assert _athletes(shared) == {"ir": "5"}


def test_a_name_finding_an_id_sleeper_gives_somebody_else_finds_nobody() -> None:
    roster = [Athlete(athlete_id="5", name="Out Man", club="WSH")]

    assert _athletes(roster) == {"ir": "5"}


def test_a_return_date_is_the_first_week_with_a_game_on_or_after_it() -> None:
    assert return_week(date(2026, 9, 14), SCHEDULE) == 1  # the week's Monday game
    assert return_week(date(2026, 9, 15), SCHEDULE) == 2  # the Tuesday after it
    assert return_week(date(2026, 9, 18), SCHEDULE) is None  # past the last game


def test_a_return_reads_as_a_week_and_falls_back_to_the_day() -> None:
    assert short_return(date(2026, 9, 13), SCHEDULE) == "wk 1"
    assert short_return(date(2027, 3, 1), SCHEDULE) == "1 Mar"
    assert long_return(date(2026, 9, 13), SCHEDULE) == "~13 Sep · wk 1"
    assert long_return(date(2027, 3, 1), SCHEDULE) == "~1 Mar"


def test_a_projection_takes_the_reports_designation_and_keeps_his_points() -> None:
    projection = proj("hall", "Breece Hall", "RB", 11.2, team="NYJ", opp="LV")

    [after] = reported({"hall": projection}, {"hall": "Questionable"}).values()

    assert (after.injury_status, after.points, after.opponent) == ("Questionable", 11.2, "LV")


def test_a_projection_the_report_does_not_name_is_left_as_published() -> None:
    projection = proj("wash", "Antonio Williams", "WR", 7.1, team="WAS")

    assert reported({"wash": projection}, {"hall": "Out"})["wash"] is projection


def test_the_catalog_takes_the_reports_designation_without_changing_sleepers() -> None:
    updated = catalog(PLAYERS, {"hall": "Questionable"}, lambda meta, status: replace(meta, injury_status=status))

    assert updated["hall"].injury_status == "Questionable"
    assert PLAYERS["hall"].injury_status == "Out"
