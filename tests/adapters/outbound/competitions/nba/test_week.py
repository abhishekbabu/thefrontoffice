"""Tests for a basketball week as the page reads it: `nba/week.py`.

Its real games are read from Sleeper's schedule, where a matchup window is
counted on date labels while "has it happened" is decided in the zone the
league schedules by.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from support.nba import FakeSleeperNBA, make_player

from thefrontoffice.adapters.outbound.competitions.nba import week
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, FIELD_GOALS, PACIFIC, POINTS, TURNOVERS
from thefrontoffice.adapters.outbound.competitions.nba.week import SleeperNBASchedule
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, Pairing, StatCategory, YahooLine
from thefrontoffice.domain.models import WeekRange


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


def test_the_games_left_are_the_windows_games_yet_to_tip_off_once_each() -> None:
    schedule = _schedule(
        schedule=[
            _sched("2026-02-09"),
            _sched("2026-02-10", status="in_game", home="BOS", away="NYK"),
            _sched("2026-02-10"),
            _sched("2026-02-14"),
            _sched("2026-02-16"),
        ]
    )

    left = schedule.games_left(WINDOW_START, WINDOW_END, now=NOW)

    assert [(g.date, g.home) for g in left] == [("2026-02-10", "DEN"), ("2026-02-14", "DEN")]


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


def test_todays_games_are_the_pacific_days_whatever_has_tipped_off_once_each() -> None:
    """Read in Pacific, the zone the league schedules by: past midnight on the 11th in UTC is still the 10th's
    slate there, and a game under way or over is still today's."""
    schedule = _schedule(
        schedule=[
            _sched("2026-02-09"),
            _sched("2026-02-10", status="complete", home="BOS", away="NYK"),
            _sched("2026-02-10", status="in_game"),
            _sched("2026-02-11"),
        ]
    )
    found = schedule.games_today(now=datetime(2026, 2, 11, 1, 30, tzinfo=UTC))

    assert found is not None
    day, games = found
    assert (day, [(g.home, g.status) for g in games]) == (date(2026, 2, 10), [("DEN", "in_game"), ("BOS", "complete")])


def test_todays_games_are_unknown_rather_than_none_when_the_schedule_will_not_load() -> None:
    assert _schedule(error=SleeperAPIError("down")).games_today(now=NOW) is None


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
    reading = Reading(
        player=player, line={POINTS.label: 20.0}, per_game=39.4, games=0, average=YahooLine(points="35.20")
    )

    [row] = week.side("Mine", "", "", [player], {"hg": reading}, by_points=True).lineup

    assert (row.value, row.detail, row.tone) == ("0G · 35.20 fpts/g", "PG · GSW · O", "warning")


def test_a_row_with_no_reading_shows_his_status() -> None:
    player = make_player("Unknown", status="GTD", selected_position="BN")

    [row] = week.side("Mine", "", "", [player]).bench

    assert (row.value, row.detail) == ("GTD", "PF · LAL")


def test_a_week_played_reads_in_the_leagues_categories_and_in_its_order() -> None:
    scored = [StatCategory(FIELD_GOALS.yahoo_stat, "FG%"), StatCategory(POINTS.yahoo_stat, "PTS")]
    player = make_player("A", stats={POINTS.yahoo_stat: "143", FIELD_GOALS.yahoo_stat: "0.456", "99": "7"})

    assert [(s.label, s.value) for s in week.line(player, scored)] == [("FG%", ".456"), ("PTS", "143")]
    assert week.line(make_player("B", stats={POINTS.yahoo_stat: "-"}), scored) == []


def test_a_week_played_row_carries_its_line_as_columns_and_no_line_where_he_played_none() -> None:
    scored = [StatCategory(FIELD_GOALS.yahoo_stat, "FG%"), StatCategory(POINTS.yahoo_stat, "PTS")]
    played = make_player("A", selected_position="PG", stats={POINTS.yahoo_stat: "143", FIELD_GOALS.yahoo_stat: ".5"})
    idle = make_player("B", selected_position="C", stats={POINTS.yahoo_stat: "-"})

    a, b = week.side("Mine", "", "", [played, idle], scored=scored).lineup

    assert [(s.label, s.value) for s in a.line] == [("FG%", ".500"), ("PTS", "143")]
    assert a.detail == "PF · LAL"
    assert (b.line, b.detail) == ([], "PF · LAL · no games")


def test_a_category_lines_rates_read_as_every_page_prints_them() -> None:
    scored = [StatCategory(FIELD_GOALS.yahoo_stat, "FG%"), StatCategory(POINTS.yahoo_stat, "PTS")]

    fg, pts = week.categories(scored, {"5": "0.85", "12": "301"}, {"5": "-", "12": ""})

    assert (fg.mine, fg.theirs, pts.mine, pts.theirs) == (".850", "-", "301", "")


# ── a schedule not yet final ────────────────────────────────────────────


def _season(*empty: date, start: date = date(2026, 10, 20), end: date = date(2027, 4, 12)) -> list[ScheduledGame]:
    """Seven games a day from `start` to `end`, none on the days in `empty`."""
    days = (start + n * week.ONE_DAY for n in range((end - start).days + 1))
    return [_sched(day.isoformat(), away=f"A{i}") for day in days if day not in empty for i in range(7)]


CUP_GAP = [date(2026, 12, day) for day in range(4, 12)]
"""4-11 December with no games yet: the clubs knocked out of the Cup, not scheduled."""


def test_a_run_of_empty_days_in_the_cup_knockout_weeks_is_unscheduled_inside_the_window() -> None:
    unscheduled = week.unsettled(_season(*CUP_GAP), date(2026, 11, 30), date(2026, 12, 6))

    assert unscheduled == CUP_GAP[:3]


def test_a_run_crossing_the_windows_start_still_counts() -> None:
    """The 11th alone in a window starting that day is the end of an eight-day run, not a quiet day."""
    assert week.unsettled(_season(*CUP_GAP), date(2026, 12, 11), date(2026, 12, 13)) == [date(2026, 12, 11)]


def test_a_day_or_two_without_games_is_a_quiet_stretch_not_an_unscheduled_one() -> None:
    """A Cup semi-final night has two games, and the final one: the schedule is final all the same."""
    games = _season(date(2026, 12, 13), date(2026, 12, 16), date(2026, 12, 17))

    assert week.unsettled(games, date(2026, 12, 1), date(2026, 12, 20)) == []


def test_the_all_star_break_is_as_long_a_gap_and_final() -> None:
    gap = [date(2027, 2, day) for day in range(12, 18)]

    assert week.unsettled(_season(*gap), date(2027, 2, 8), date(2027, 2, 21)) == []


def test_days_before_the_season_opens_or_after_it_closes_are_not_unscheduled() -> None:
    games = _season(start=date(2026, 12, 8), end=date(2026, 12, 9))

    assert week.unsettled(games, date(2026, 12, 1), date(2026, 12, 20)) == []
    assert week.unsettled([], date(2026, 12, 1), date(2026, 12, 20)) == []


def test_the_fixtures_note_names_the_days_unscheduled_and_is_empty_without_any() -> None:
    assert "4-6 Dec" in week.not_final(CUP_GAP[:3])
    assert week.not_final([]) == ""


def test_the_header_says_the_schedule_is_not_final_while_days_are_unscheduled() -> None:
    found = Pairing(date(2026, 11, 30), date(2026, 12, 13), _side("1"), replace(_side("2"), team_key="t2"))
    weeks = WeekRange(week=7, current=7, first=1, last=20)

    assert week.NOT_FINAL in week.board(found, weeks, {}, None, None, None, unscheduled=CUP_GAP[:3]).headline
    assert week.NOT_FINAL not in week.board(found, weeks, {}, None, None, None).headline


def test_sleepers_schedule_reads_the_whole_season_and_a_failed_one_as_final() -> None:
    window = (date(2026, 11, 30), date(2026, 12, 13))

    assert _schedule(schedule=_season(*CUP_GAP)).unscheduled(*window) == CUP_GAP
    assert _schedule(error=SleeperAPIError("down")).unscheduled(*window) == []
