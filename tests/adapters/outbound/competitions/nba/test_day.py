"""A basketball day: both sides as slotted on it, each player's line or projection, the day's score, what to fix."""

from collections.abc import Mapping, Sequence
from datetime import date

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba import day as nba_day
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES, TURNOVERS, Line
from thefrontoffice.adapters.outbound.competitions.nba.week import Stage
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, Pairing, StatCategory, YahooPlayer
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import DayRange, Spot, Summary, WeekRange

MONDAY, SUNDAY = date(2026, 11, 23), date(2026, 11, 29)
WEDNESDAY = date(2026, 11, 25)
SCORED = [StatCategory(c.yahoo_stat, c.label, fewer_wins=c is TURNOVERS) for c in CATEGORIES]
WEIGHTS = {"12": 1.0, "15": 1.2, "16": 1.5}
"""Points, rebounds and assists: a points league."""
SLOTS = ("PG", "C", "Util")

FOUND = Pairing(
    start=MONDAY,
    end=SUNDAY,
    mine=MatchupSide(team_key="t.1", name="Mine", points="", stats={}),
    opponent=MatchupSide(team_key="t.2", name="Theirs", points="", stats={}),
)
WEEKS = WeekRange(week=6, current=6, first=1, last=21)


def game(home: str, away: str, status: str = "pre_game") -> ScheduledGame:
    return ScheduledGame(week=0, date=WEDNESDAY.isoformat(), home=home, away=away, status=status)


def line(pts: int, reb: int = 0, made: int = 0, taken: int = 0, to: int = 0) -> dict[str, str]:
    """A day's line as Yahoo prints it: points, rebounds, field goals as '7/15' and their rate, turnovers."""
    return {
        "12": str(pts),
        "15": str(reb),
        "9004003": f"{made}/{taken}",
        "5": f"{made / taken:.3f}" if taken else "-",
        "19": str(to),
    }


SAT_OUT = {"12": "0", "15": "0", "9004003": "0/0", "5": "-", "19": "0"}
"""A game he never checked into: Yahoo prints a nought in every count."""

TO_COME = {"12": "-", "15": "-", "9004003": "-/-", "5": "-"}


def a_day(
    stage: Stage,
    games: Sequence[ScheduledGame] | None = (),
    projected: Mapping[str, Line] | None = None,
) -> nba_day.Day:
    return nba_day.Day(
        day=WEDNESDAY,
        stage=stage,
        games=games,
        projected=projected or {},
        slots=SLOTS,
    )


def board(
    mine: list[YahooPlayer],
    theirs: list[YahooPlayer],
    day: nba_day.Day,
    by_points: bool = False,
) -> Summary:
    span = DayRange(day=day.day, first=MONDAY, last=SUNDAY, today=WEDNESDAY)
    return nba_day.board(
        FOUND,
        WEEKS,
        span,
        {"t.1": "4-1", "t.2": "2-3"},
        (mine, theirs),
        None if by_points else SCORED,
        WEIGHTS if by_points else None,
        day,
    )


def rows(summary: Summary, side: str = "mine") -> dict[str, Spot]:
    found = summary.mine if side == "mine" else summary.opponent
    assert found is not None
    return {spot.player: spot for spot in (*found.lineup, *found.bench, *found.reserve)}


def stats(summary: Summary) -> dict[str, str]:
    return {stat.label: stat.value for stat in summary.headline}


# ── which day ────────────────────────────────────────────────────────────


def test_a_week_opens_on_today_where_it_holds_it_and_on_its_first_day_where_it_does_not() -> None:
    assert nba_day.pick(None, MONDAY, SUNDAY, WEDNESDAY) == WEDNESDAY
    assert nba_day.pick(None, MONDAY, SUNDAY, date(2026, 12, 2)) == MONDAY
    assert nba_day.pick(SUNDAY, MONDAY, SUNDAY, WEDNESDAY) == SUNDAY


def test_a_day_outside_the_week_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        nba_day.pick(date(2026, 11, 30), MONDAY, SUNDAY, WEDNESDAY)


def test_a_weeks_days_run_from_its_first_to_its_last() -> None:
    assert nba_day.days(MONDAY, SUNDAY) == [date(2026, 11, d) for d in range(23, 30)]


@pytest.mark.parametrize(
    ("figures", "did"),
    [(TO_COME, False), (SAT_OUT, False), (line(0, made=0, taken=2), True), (line(12), True)],
)
def test_a_player_has_a_line_once_he_has_done_anything(figures: dict[str, str], did: bool) -> None:
    assert nba_day.played(make_player("A", stats=figures)) is did


# ── a day played ─────────────────────────────────────────────────────────


def test_a_day_played_totals_only_the_starters_and_says_what_the_bench_left_out() -> None:
    games = [game("LAL", "BOS", "complete"), game("DEN", "MIA", "complete")]
    mine = [
        make_player("Guard", team="LAL", selected_position="PG", stats=line(20, 5, made=8, taken=16, to=3)),
        make_player("Center", team="DEN", selected_position="C", stats=line(10, 12, made=4, taken=4, to=1)),
        make_player("Benched", team="BOS", selected_position="BN", stats=line(30, 9, made=12, taken=20)),
    ]
    theirs = [make_player("Rival", team="MIA", selected_position="PG", stats=line(25, 4, made=10, taken=20, to=2))]

    summary = board(mine, theirs, a_day("played", games))

    figures = {c.name: (c.mine, c.theirs, c.lead) for c in summary.categories}
    assert figures["PTS"] == ("30", "25", "mine")
    assert figures["REB"] == ("17", "4", "mine")
    assert figures["FG%"] == (".600", ".500", "mine")  # 12 of 20, not the mean of .500 and 1.000
    assert figures["TO"] == ("4", "2", "theirs")
    assert summary.mine is not None and "30p" in summary.mine.detail and "9r" in summary.mine.detail
    assert stats(summary)["Starts"] == "2 – 1"
    assert summary.days is not None and summary.days.day == WEDNESDAY


def test_a_game_sat_out_reads_as_one_and_counts_no_start() -> None:
    games = [game("LAL", "BOS", "complete")]
    mine = [make_player("Rested", team="LAL", selected_position="PG", stats=SAT_OUT)]

    summary = board(mine, [], a_day("played", games))

    assert rows(summary)["Rested"].value == nba_day.DNP
    assert rows(summary)["Rested"].line == []
    assert stats(summary)["Starts"] == "0 – 0"


def test_a_day_played_flags_nothing_to_fix_and_projects_nobody() -> None:
    games = [game("LAL", "BOS", "complete")]
    mine = [
        make_player("Idle", team="NYK", selected_position="PG", stats=TO_COME),
        make_player("Benched", team="LAL", selected_position="BN", stats=line(15)),
    ]

    summary = board(mine, [], a_day("played", games, {"benched": {"PTS": 20.0}}))

    assert not any(row.mark or row.tone == "warning" or row.projection for row in rows(summary).values())
    assert "Lineup" not in stats(summary)


def test_a_points_day_played_scores_each_side_in_fantasy_points() -> None:
    games = [game("LAL", "BOS", "complete")]
    mine = [
        make_player("Starter", team="LAL", selected_position="PG", points="31.20", stats=line(20)),
        make_player("Benched", team="BOS", selected_position="BN", points="18.40", stats=line(12)),
    ]
    theirs = [make_player("Rival", team="BOS", selected_position="PG", points="40.10", stats=line(30))]

    summary = board(mine, theirs, a_day("played", games), by_points=True)

    row = rows(summary)["Starter"]
    assert (row.scored, row.scoring) == ("31.2", "final")
    assert summary.categories == []
    assert stats(summary)["Day"] == "31.2 – 40.1"
    assert summary.mine is not None and "18.4" in summary.mine.detail


# ── the day being played ─────────────────────────────────────────────────


def test_the_day_being_played_says_which_games_are_on_or_over_and_shows_what_is_in() -> None:
    games = [game("LAL", "BOS", "in_game"), game("DEN", "MIA")]
    mine = [
        make_player("On", team="LAL", selected_position="PG", points="12.00", stats=line(8)),
        make_player("Later", team="DEN", selected_position="C", stats=TO_COME),
    ]

    summary = board(mine, [], a_day("playing", games, {"later": {"PTS": 20.0, "REB": 10.0}}), by_points=True)

    on, later = rows(summary)["On"], rows(summary)["Later"]
    assert (on.scoring, on.scored) == ("live", "12")
    assert "live" in on.today
    assert (later.scoring, later.projection) == ("projected", "32.0")
    assert summary.mine is not None and "44.0 proj" in summary.mine.points  # 12 in, 32 to come


def test_a_bench_player_whose_game_is_under_way_can_no_longer_be_started() -> None:
    games = [game("LAL", "BOS", "in_game")]
    mine = [
        make_player("Idle", team="NYK", position="C", selected_position="C", stats=TO_COME),
        make_player("Locked", team="LAL", position="C", selected_position="BN", stats=line(4)),
    ]

    summary = board(mine, [], a_day("playing", games))

    assert rows(summary)["Locked"].mark == ""
    assert "Lineup" not in stats(summary)


# ── a day to come ────────────────────────────────────────────────────────


def test_a_bench_player_with_a_game_who_would_add_a_start_is_marked_and_the_idle_starter_flagged() -> None:
    """C sits idle; the bench center plays and fits it, the bench point guard plays but every slot he fits is full."""
    games = [game("LAL", "BOS"), game("DEN", "MIA")]
    mine = [
        make_player("Point", team="LAL", position="PG", selected_position="PG", stats=TO_COME),
        make_player("Idle Big", team="NYK", position="C", selected_position="C", stats=TO_COME),
        make_player("Wing", team="BOS", position="SF", selected_position="Util", stats=TO_COME),
        make_player("Bench Big", team="DEN", position="C", selected_position="BN", stats=TO_COME),
        make_player("Bench Guard", team="MIA", position="PG", selected_position="BN", stats=TO_COME),
    ]

    summary = board(mine, [], a_day("to come", games))

    found = rows(summary)
    assert found["Bench Big"].mark == nba_day.START
    assert found["Bench Guard"].mark == ""
    assert (found["Idle Big"].tone, found["Idle Big"].idle) == ("warning", True)
    assert stats(summary)["Lineup"].startswith("1")
    assert stats(summary)["Starts"] == "2 – 0"


def test_two_bench_players_wanting_the_one_open_slot_count_as_one_start() -> None:
    games = [game("LAL", "BOS"), game("DEN", "MIA")]
    mine = [
        make_player("Point", team="LAL", position="PG", selected_position="PG", stats=TO_COME),
        make_player("Idle Big", team="NYK", position="C", selected_position="C", stats=TO_COME),
        make_player("Wing", team="BOS", position="SF", selected_position="Util", stats=TO_COME),
        make_player("Big One", team="DEN", position="C", selected_position="BN", stats=TO_COME),
        make_player("Big Two", team="MIA", position="C", selected_position="BN", stats=TO_COME),
    ]

    summary = board(mine, [], a_day("to come", games))

    assert {name for name, row in rows(summary).items() if row.mark} == {"Big One", "Big Two"}
    assert stats(summary)["Lineup"].startswith("1")


def test_an_idle_starter_nobody_could_replace_is_left_unflagged() -> None:
    games = [game("LAL", "BOS")]
    mine = [
        make_player("Point", team="LAL", position="PG", selected_position="PG", stats=TO_COME),
        make_player("Idle Big", team="NYK", position="C", selected_position="C", stats=TO_COME),
    ]

    summary = board(mine, [], a_day("to come", games))

    assert rows(summary)["Idle Big"].tone == "neutral"
    assert "Lineup" not in stats(summary)


def test_a_starter_ruled_out_is_flagged_by_his_status_and_never_marked_to_start() -> None:
    games = [game("LAL", "BOS")]
    mine = [
        make_player("Hurt", team="LAL", position="PG", selected_position="PG", status="O", stats=TO_COME),
        make_player("Also Hurt", team="BOS", position="C", selected_position="BN", status="INJ", stats=TO_COME),
    ]

    summary = board(mine, [], a_day("to come", games))

    assert (rows(summary)["Hurt"].value, rows(summary)["Hurt"].tone) == ("O", "warning")
    assert rows(summary)["Also Hurt"].mark == ""


def test_only_your_own_side_is_told_what_to_fix() -> None:
    games = [game("DEN", "MIA")]
    theirs = [
        make_player("Idle Big", team="NYK", position="C", selected_position="C", stats=TO_COME),
        make_player("Bench Big", team="DEN", position="C", selected_position="BN", stats=TO_COME),
    ]

    summary = board([], theirs, a_day("to come", games))

    assert not any(row.mark or row.tone == "warning" for row in rows(summary, "opponent").values())


def test_a_category_day_to_come_shows_each_game_projected_and_no_categories_yet() -> None:
    games = [game("LAL", "BOS")]
    mine = [make_player("Guard", team="LAL", selected_position="PG", stats=TO_COME)]

    summary = board(mine, [], a_day("to come", games, {"guard": {"PTS": 21.4, "REB": 6.0, "AST": 7.2}}))

    assert rows(summary)["Guard"].value == "21p 6r 7a"
    assert summary.categories == []
    assert "Day" not in stats(summary)


def test_a_day_whose_schedule_would_not_load_says_nothing_of_who_plays() -> None:
    mine = [make_player("Guard", team="LAL", selected_position="PG", stats=TO_COME)]

    summary = board(mine, [], a_day("to come", None))

    row = rows(summary)["Guard"]
    assert (row.today, row.idle) == ("", False)
    assert "Starts" not in stats(summary)
