"""Tests for ESPN's injury report joined to a platform's players: `competitions/injuries.py`."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from thefrontoffice.adapters.outbound.competitions.injuries import (
    BODY_PART,
    PlayerInjuries,
    approximately,
    by_club,
    designation,
    in_words,
    injury_stats,
    matched,
    unsure,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport

CLUBS = by_club([("GS", "Stephen Curry", "curry"), ("SA", "Keldon Johnson", "kj"), ("SA", "Keldon Johnson", "kj2")])


def _report(
    name: str,
    club: str,
    status: str = "Out",
    athlete_id: str = "",
    updated: datetime = datetime(2026, 11, 17, tzinfo=UTC),
) -> InjuryReport:
    return InjuryReport(name=name, club=club, status=status, updated=updated, athlete_id=athlete_id)


def test_a_name_finds_its_player_on_his_own_club_whatever_its_suffix() -> None:
    assert set(matched([_report("Stephen Curry Jr.", "GS")], CLUBS, {})) == {"curry"}


def test_a_name_on_another_club_is_not_him() -> None:
    assert matched([_report("Stephen Curry", "SA")], CLUBS, {}) == {}


def test_a_name_two_players_on_one_club_share_is_nobodys() -> None:
    assert CLUBS["SA"] == {"keldon johnson": None}
    assert matched([_report("Keldon Johnson", "SA")], CLUBS, {}) == {}


def test_one_player_listed_twice_is_still_his_and_a_third_namesake_still_nobodys() -> None:
    assert by_club([("GS", "Stephen Curry", "curry"), ("GS", "Stephen Curry", "curry")]) == {
        "GS": {"stephen curry": "curry"}
    }
    assert by_club([("SA", "K J", "a"), ("SA", "K J", "b"), ("SA", "K J", "a")]) == {"SA": {"k j": None}}


def test_an_espn_id_the_platform_carries_wins_over_the_name() -> None:
    assert set(matched([_report("Steph Curry", "GS", athlete_id="3975")], CLUBS, {"3975": "kj"})) == {"kj"}


def test_a_name_whose_player_carries_another_espn_id_is_somebody_else() -> None:
    assert matched([_report("Stephen Curry", "GS", athlete_id="222")], CLUBS, {"111": "curry"}) == {}


def test_two_rows_for_one_player_keep_the_latest() -> None:
    older = _report("Stephen Curry", "GS", "Out", updated=datetime(2026, 11, 1, tzinfo=UTC))
    newer = _report("Stephen Curry", "GS", "Day-To-Day")

    assert matched([newer, older], CLUBS, {})["curry"].status == "Day-To-Day"


def _hurt(status: str = "Out", comment: str = "Curry (calf) won't play Friday.") -> PlayerInjuries:
    report = replace(
        _report("Stephen Curry", "GS", status),
        returns=date(2026, 11, 22),
        injury="Left calf, strain",
        comment=comment,
        url="https://espn.example/curry",
    )
    return PlayerInjuries(by_player={"curry": report})


def test_the_drawer_shows_the_injury_an_approximate_return_and_the_latest_word_linked() -> None:
    stats = {s.label: s for s in _hurt().stats("curry")}

    assert (stats["Status"].value, stats["Status"].tone) == ("Out", "warning")
    assert stats[BODY_PART].value == "Left calf, strain"
    assert stats["Back"].value == approximately(date(2026, 11, 22)) == "~22 Nov"
    [update] = [s for s in stats.values() if s.url]
    assert (update.label, update.value, update.url) == (
        "Tue 17 Nov",
        "Curry (calf) won't play Friday.",
        "https://espn.example/curry",
    )


def test_a_sport_reads_the_return_in_its_own_calendar() -> None:
    stats = {s.label: s.value for s in _hurt().stats("curry", lambda back: f"day {back.day}")}

    assert stats["Back"] == "day 22"


def test_a_comment_that_only_repeats_the_status_is_left_out() -> None:
    assert not any(s.url for s in _hurt("Questionable", "questionable").stats("curry"))


def test_a_cleared_player_has_no_injury_to_show() -> None:
    injuries = _hurt("Active")

    assert injuries.stats("curry") == []
    assert injuries.returns("curry") is None
    assert injuries.of("nobody") is None


def test_a_hurt_player_has_his_return_and_one_off_the_report_none() -> None:
    assert _hurt().returns("curry") == date(2026, 11, 22)
    assert PlayerInjuries().returns("curry") is None


def test_any_platforms_injury_reads_the_same_and_an_undated_word_is_the_latest() -> None:
    """FPL reports its own injuries, with no ESPN row behind them: the group is built from the parts."""
    stats = injury_stats("injured", injury="Knock", returns=date(2026, 11, 23), comment="Expected back 23 Nov")

    assert [(s.label, s.value) for s in stats] == [
        ("Status", "injured"),
        (BODY_PART, "Knock"),
        ("Back", "~23 Nov"),
        ("Latest", "Expected back 23 Nov"),
    ]


def test_a_code_reads_in_words_whatever_its_case_and_an_unknown_one_as_written() -> None:
    words = {"O": "Out"}

    assert [in_words(code, words) for code in ("O", "o", "NEW", "")] == ["Out", "Out", "NEW", ""]


def test_a_platforms_designation_says_only_what_it_has() -> None:
    assert designation("") == []
    assert [(s.label, s.value) for s in designation("Out", "Knee")] == [("Status", "Out"), (BODY_PART, "Knee")]
    assert [s.label for s in designation("", "Knee")] == [BODY_PART]


@pytest.mark.parametrize(
    ("comment", "returns", "open_"),
    [
        ("Robinson (quadriceps) is considered day-to-day as he progresses in his rehab.", date(2026, 11, 27), True),
        ("He remains out indefinitely.", date(2026, 12, 1), True),
        ("Coach says he will return for Friday's game.", date(2026, 11, 27), False),
        ("Coach says he will return soon.", None, True),
    ],
)
def test_a_return_is_unsure_without_a_date_or_where_the_latest_word_leaves_it_open(
    comment: str, returns: date | None, open_: bool
) -> None:
    report = replace(_report("Duncan Robinson", "DET"), comment=comment, returns=returns)

    assert unsure(report) is open_
