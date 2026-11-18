"""Tests for the latest injury report, joined to Sleeper: `nfl/injuries.py`."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

from support.nfl import SEASON_SCHEDULE, proj

from thefrontoffice.adapters.outbound.competitions.nfl.injuries import (
    BODY_PART,
    PlayerInjuries,
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
    "kc1": PlayerMeta(player_id="kc1", name="Chris Jones", position="WR", team="KC"),
    "kc2": PlayerMeta(player_id="kc2", name="Chris Jones", position="TE", team="KC"),
}


SCHEDULE = {w: [g for g in SEASON_SCHEDULE if g.week == w] for w in {g.week for g in SEASON_SCHEDULE}}


def _report(
    name: str, club: str, status: str, athlete_id: str = "", updated: datetime = datetime(2026, 10, 27, 13, tzinfo=UTC)
) -> InjuryReport:
    return InjuryReport(name=name, club=club, status=status, updated=updated, athlete_id=athlete_id)


def _designations(reports: Sequence[InjuryReport], espn_ids: dict[str, str] | None = None) -> dict[str, str]:
    return designations(matched(reports, PLAYERS, espn_ids or {}))


def test_the_report_names_a_player_by_his_name_on_his_own_club() -> None:
    assert _designations([_report("Breece Hall", "NYJ", "Questionable")]) == {"hall": "Questionable"}


def test_a_club_is_read_in_espns_spelling() -> None:
    assert _designations([_report("Antonio Williams", "WSH", "Out")]) == {"wash": "Out"}


def test_a_player_of_the_same_name_on_another_club_is_not_him() -> None:
    assert _designations([_report("Breece Hall", "BUF", "Out")]) == {}


def test_a_name_two_players_on_a_club_share_is_nobodys() -> None:
    assert _designations([_report("Chris Jones", "KC", "Out")]) == {}


def test_a_player_cleared_to_play_carries_no_designation() -> None:
    assert _designations([_report("Breece Hall", "NYJ", "Active")]) == {"hall": ""}


def test_a_designation_the_rules_have_no_word_for_changes_nothing() -> None:
    assert _designations([_report("Breece Hall", "NYJ", "Day-To-Day")]) == {}


def test_a_long_ruling_reads_in_sleepers_words() -> None:
    assert _designations([_report("Breece Hall", "NYJ", "Injured Reserve")]) == {"hall": "IR"}


def test_espns_id_wins_over_a_name() -> None:
    """Sleeper's espn_id names him whatever ESPN calls him, and whichever club the name would find."""
    report = _report("Breece Hall Jr.", "NYJ", "Out", athlete_id="4427366")

    assert set(matched([report], PLAYERS, {"4427366": "wash"})) == {"wash"}


def test_a_name_match_carrying_another_espn_id_is_somebody_else() -> None:
    players = {**PLAYERS, "hall": replace(PLAYERS["hall"], espn_id="111")}

    assert matched([_report("Breece Hall", "NYJ", "Out", athlete_id="222")], players, {"111": "hall"}) == {}


def test_a_shared_name_with_no_id_match_still_matches_nobody() -> None:
    assert matched([_report("Chris Jones", "KC", "Out", athlete_id="999")], PLAYERS, {}) == {}


def test_two_rows_for_one_player_keep_the_latest() -> None:
    older = _report("Breece Hall", "NYJ", "Out", updated=datetime(2026, 10, 20, tzinfo=UTC))
    newer = _report("Breece Hall", "NYJ", "Questionable")

    assert _designations([newer, older]) == {"hall": "Questionable"}


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


def _hurt(status: str = "Injured Reserve", comment: str = "Hall (knee) had surgery.") -> PlayerInjuries:
    report = replace(
        _report("Breece Hall", "NYJ", status),
        returns=date(2026, 9, 13),
        injury="Right knee, surgery",
        comment=comment,
        url="https://espn.example/hall",
    )
    return PlayerInjuries(by_player={"hall": report})


def test_the_drawer_shows_the_injury_its_return_and_the_latest_word_linked() -> None:
    stats = {s.label: s for s in _hurt().stats("hall", SCHEDULE)}

    assert stats["Status"].value == "Injured Reserve"
    assert stats[BODY_PART].value == "Right knee, surgery"
    assert stats["Back"].value == "~13 Sep · wk 1"
    [update] = [s for s in stats.values() if s.url]
    assert (update.value, update.url) == ("Hall (knee) had surgery.", "https://espn.example/hall")


def test_a_comment_that_only_repeats_the_status_is_left_out() -> None:
    assert not any(s.url for s in _hurt("Questionable", "questionable").stats("hall", SCHEDULE))


def test_a_cleared_player_has_no_injury_to_show() -> None:
    injuries = _hurt("Active")

    assert injuries.stats("hall", SCHEDULE) == []
    assert injuries.returns("hall") is None
    assert injuries.of("nobody") is None


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
