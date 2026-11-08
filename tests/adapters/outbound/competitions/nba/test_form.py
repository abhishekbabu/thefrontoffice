"""Tests for basketball's recent form and remaining games, read from Sleeper.

The rules that make the numbers mean anything: percentages summed rather than
averaged, a window withheld until it can be filled, a game nobody played kept
out of the average, and a matchup window counted on date labels while "has it
happened" is decided in the zone the league schedules by.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from support.nba import FakeSleeperNBA

from thefrontoffice.adapters.outbound.competitions.nba.form import SleeperNBAForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta, ScheduledGame

PACIFIC = ZoneInfo("America/Los_Angeles")


def _game(day: str, **stats: float) -> NBAGameLog:
    return NBAGameLog(player_id="p1", date=day, opponent="LAL", stats=stats)


def _form(**kwargs: Any) -> SleeperNBAForm:
    return SleeperNBAForm(client=FakeSleeperNBA(**kwargs), season="2026")


# ── the nine-category line ──────────────────────────────────────────────


def test_percentages_come_from_summed_attempts_not_averaged_rates() -> None:
    """The two differ whenever attempts vary between games, which is exactly
    when the number matters: 1/1 and 2/10 is 27%, not 60%."""
    line = nine_cat([_game("2026-01-02", fgm=1, fga=1), _game("2026-01-01", fgm=2, fga=10)])

    assert line["FG%"] == pytest.approx(3 / 11)


def test_a_category_nobody_recorded_averages_to_zero() -> None:
    """Sleeper omits a key rather than publishing nought, so an absent steal
    has to read as none rather than as missing data."""
    line = nine_cat([_game("2026-01-02", pts=10), _game("2026-01-01", pts=20)])

    assert line["PTS"] == 15.0
    assert line["STL"] == 0.0


def test_no_attempts_is_no_percentage_rather_than_zero() -> None:
    """Nothing attempted is a different thing from 0%, and the drawer shows it as absent."""
    assert "FT%" not in nine_cat([_game("2026-01-01", pts=2)])


def test_the_line_is_keyed_by_every_category_label() -> None:
    """The drawer and the prompt read the line by these labels; a key spelled any
    other way is a figure nobody finds."""
    line = nine_cat([_game("2026-01-01", pts=2, fgm=1, fga=2, ftm=1, fta=1)])

    assert set(line) == {c.label for c in CATEGORIES}


# ── the windows ─────────────────────────────────────────────────────────


def _run(n: int) -> dict[str, list[NBAGameLog]]:
    return {"p1": [_game(f"2026-01-{i + 1:02d}", pts=10) for i in range(n)]}


def test_a_window_is_reported_only_once_it_can_be_filled() -> None:
    """Five games averaged into a "last fifteen" is a different number wearing
    the same label."""
    stats = _form(logs=_run(7)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"last_5"}


def test_every_window_appears_once_there_are_enough_games() -> None:
    stats = _form(logs=_run(20)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"last_5", "last_10", "last_15"}


def test_a_player_with_no_games_has_no_form_rather_than_zeros() -> None:
    assert _form(logs={}).get_player_stats("Nikola Jokic") is None


def test_a_name_that_cannot_be_matched_carries_no_form() -> None:
    """Yahoo and Sleeper share no identifier, so an unmatched player takes
    nothing rather than borrowing somebody else's line."""
    assert _form(logs=_run(20)).get_player_stats("Someone Else Entirely") is None


def test_an_accented_name_still_matches() -> None:
    """Sleeper spells him Jokić; Yahoo does not."""
    form = SleeperNBAForm(
        client=FakeSleeperNBA(
            logs=_run(20),
            catalog={"p1": PlayerMeta(player_id="p1", name="Nikola Jokić", position="C", team="DEN")},
        ),
        season="2026",
    )

    assert form.get_player_stats("Nikola Jokic") is not None


def test_a_failed_lookup_leaves_the_report_without_form_rather_than_failing() -> None:
    """Form is enrichment: a report without it is thinner, not wrong."""
    assert _form(error=SleeperAPIError("down")).get_player_stats("Nikola Jokic") is None


# ── remaining games ─────────────────────────────────────────────────────


def _sched(day: str, status: str = "pre_game", home: str = "DEN", away: str = "LAL") -> ScheduledGame:
    return ScheduledGame(week=1, date=day, home=home, away=away, status=status)


WINDOW_START = date(2026, 2, 9)
WINDOW_END = date(2026, 2, 15)
NOW = datetime(2026, 2, 10, 12, 0, tzinfo=PACIFIC)


def test_games_outside_the_matchup_window_are_not_counted() -> None:
    form = _form(schedule=[_sched("2026-02-08"), _sched("2026-02-12"), _sched("2026-02-16")])

    assert form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_game_already_in_the_past_is_not_remaining() -> None:
    form = _form(schedule=[_sched("2026-02-09"), _sched("2026-02-14")])

    assert form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_stale_status_cannot_resurrect_a_played_game() -> None:
    """The schedule is cached, so its statuses can be hours old. A date in the
    past settles it whatever the status still says."""
    form = _form(schedule=[_sched("2026-02-09", status="pre_game")])

    assert form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 0


def test_todays_game_turns_on_whether_it_has_tipped_off() -> None:
    tipped = _form(schedule=[_sched("2026-02-10", status="in_game")])
    waiting = _form(schedule=[_sched("2026-02-10", status="pre_game")])

    assert tipped.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 0
    assert waiting.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_club_is_counted_whether_it_is_home_or_away() -> None:
    form = _form(schedule=[_sched("2026-02-12", home="LAL", away="DEN")])

    assert form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_an_unknown_club_has_no_games_rather_than_raising() -> None:
    assert _form(schedule=[_sched("2026-02-12")]).get_remaining_games("XXX", WINDOW_START, WINDOW_END, now=NOW) == 0


def test_bulk_counts_each_club_asked_about_keyed_in_upper_case() -> None:
    form = _form(schedule=[_sched("2026-02-12", home="DEN", away="LAL")])

    assert form.get_remaining_games_bulk(["DEN", "lal"], WINDOW_START, WINDOW_END, now=NOW) == {"DEN": 1, "LAL": 1}


def test_an_unparseable_date_is_skipped_rather_than_counted() -> None:
    form = _form(schedule=[_sched("not-a-date"), _sched("2026-02-12")])

    assert form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW) == 1


def test_a_failed_schedule_raises_for_one_club_and_leaves_every_club_unknown_in_bulk() -> None:
    """Nought would read as a club with no games left; unknown is what a failed request knows."""
    form = _form(error=SleeperAPIError("down"))

    with pytest.raises(SleeperAPIError):
        form.get_remaining_games("DEN", WINDOW_START, WINDOW_END, now=NOW)
    assert form.get_remaining_games_bulk(["DEN"], WINDOW_START, WINDOW_END, now=NOW) == {}
