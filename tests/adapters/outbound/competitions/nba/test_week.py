"""Tests for a basketball week as the page reads it: `nba/week.py`.

Its real games are read from Sleeper's schedule, where a matchup window is
counted on date labels while "has it happened" is decided in the zone the
league schedules by.
"""

from datetime import date, datetime
from typing import Any

import pytest
from support.nba import FakeSleeperNBA, make_player

from thefrontoffice.adapters.outbound.competitions.nba import week
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, FIELD_GOALS, PACIFIC, POINTS, TURNOVERS
from thefrontoffice.adapters.outbound.competitions.nba.week import SleeperNBASchedule
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, StatCategory


def _side(points: str, projected: str = "") -> MatchupSide:
    return MatchupSide(team_key="t", name="T", points=points, projected=projected, stats={})


def test_a_points_week_being_played_is_scored_and_projected_in_fantasy_points() -> None:
    stats = week.points(_side("349.90", "896.45"), _side("575.80", "1107.37"), "playing")

    assert [(s.label, s.value, s.tone) for s in stats] == [
        ("Live", "349.90 – 575.80", "warning"),
        ("Projected", "896.45 – 1107.37", "warning"),
    ]


def test_a_points_week_played_is_final_with_no_projection() -> None:
    stats = week.points(_side("1185.50", "1192.10"), _side("778.80", "917.22"), "played")

    assert [(s.label, s.tone) for s in stats] == [("Final", "good")]


def test_a_points_week_to_come_has_no_score() -> None:
    assert week.points(_side("0.00", "862.79"), _side("0.00", "1116.92"), "to come") == []


def test_a_points_score_that_is_not_a_number_is_left_out() -> None:
    assert week.points(_side(""), _side(""), "playing") == []


def test_a_level_points_week_pulls_the_eye_neither_way() -> None:
    [score] = week.points(_side("100.00"), _side("100.00"), "played")

    assert score.tone == "neutral"


def test_a_sides_card_carries_what_it_scored_and_is_projected_to() -> None:
    side = _side("349.90", "896.45")

    assert week.total(side, "playing") == "349.90 pts · 896.45 proj"
    assert week.total(side, "played") == "349.90 pts"
    assert week.total(side, "to come") == "896.45 proj"


def test_a_week_is_placed_against_the_one_being_played() -> None:
    assert [week.stage(n, 5) for n in (4, 5, 6)] == ["played", "playing", "to come"]


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


# ── remaining games, from Sleeper ─────────────────────────────────────────────────────


def _sched(day: str, status: str = "pre_game", home: str = "DEN", away: str = "LAL") -> ScheduledGame:
    return ScheduledGame(week=1, date=day, home=home, away=away, status=status)


WINDOW_START = date(2026, 2, 9)
WINDOW_END = date(2026, 2, 15)
NOW = datetime(2026, 2, 10, 12, 0, tzinfo=PACIFIC)


def _schedule(**kwargs: Any) -> SleeperNBASchedule:
    return SleeperNBASchedule(client=FakeSleeperNBA(**kwargs), season="2026")


def test_games_outside_the_matchup_window_are_not_counted() -> None:
    schedule = _schedule(schedule=[_sched("2026-02-08"), _sched("2026-02-12"), _sched("2026-02-16")])

    assert schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_windows_games_are_listed_once_each_in_date_order() -> None:
    """A game is filed under both its clubs: listed under each, it would show twice."""
    schedule = _schedule(schedule=[_sched("2026-02-14"), _sched("2026-02-08"), _sched("2026-02-12")])

    assert [g.date for g in schedule.games_between(WINDOW_START, WINDOW_END)] == ["2026-02-12", "2026-02-14"]


def test_a_game_already_in_the_past_is_not_remaining() -> None:
    schedule = _schedule(schedule=[_sched("2026-02-09"), _sched("2026-02-14")])

    assert schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_stale_status_cannot_resurrect_a_played_game() -> None:
    """The schedule is cached, so its statuses can be hours old. A date in the
    past settles it whatever the status still says."""
    schedule = _schedule(schedule=[_sched("2026-02-09", status="pre_game")])

    assert schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 0


def test_todays_game_turns_on_whether_it_has_tipped_off() -> None:
    tipped = _schedule(schedule=[_sched("2026-02-10", status="in_game")])
    waiting = _schedule(schedule=[_sched("2026-02-10", status="pre_game")])

    assert tipped.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 0
    assert waiting.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_club_is_counted_whether_it_is_home_or_away() -> None:
    schedule = _schedule(schedule=[_sched("2026-02-12", home="LAL", away="DEN")])

    assert schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_an_unknown_club_has_no_games_rather_than_raising() -> None:
    assert _schedule(schedule=[_sched("2026-02-12")]).get_remaining_games("XXX", WINDOW_START, WINDOW_END, now=NOW) == 0


def test_bulk_counts_each_club_asked_about_keyed_in_upper_case() -> None:
    schedule = _schedule(schedule=[_sched("2026-02-12", home="DEN", away="LAL")])

    assert schedule.get_remaining_games_bulk(["DEN", "lal"], WINDOW_START, WINDOW_END, now=NOW) == {"DEN": 1, "LAL": 1}


def test_an_unparseable_date_is_skipped_rather_than_counted() -> None:
    schedule = _schedule(schedule=[_sched("not-a-date"), _sched("2026-02-12")])

    assert schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_failed_schedule_raises_for_one_club_and_leaves_every_club_unknown_in_bulk() -> None:
    """Nought would read as a club with no games left; unknown is what a failed request knows."""
    schedule = _schedule(error=SleeperAPIError("down"))

    with pytest.raises(SleeperAPIError):
        schedule.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW)
    assert schedule.get_remaining_games_bulk(["DEN"], WINDOW_START, WINDOW_END, now=NOW) == {}


def test_a_row_reads_his_games_left_and_a_games_value_with_his_status_beside_his_club() -> None:
    player = make_player("Hurt Guard", position="PG", team="GSW", key="hg", status="O", selected_position="PG")
    reading = Reading(player=player, line={POINTS.label: 20.0}, per_game=39.4, games=0)

    [row] = week.side("Mine", "", "", [player], {"hg": reading}, by_points=True).lineup

    assert (row.value, row.detail, row.tone) == ("0G · 39.4 fpts/g", "PG · GSW · O", "warning")


def test_a_row_with_no_reading_shows_his_status() -> None:
    player = make_player("Unknown", status="GTD", selected_position="BN")

    [row] = week.side("Mine", "", "", [player]).bench

    assert (row.value, row.detail) == ("GTD", "PF · LAL")
