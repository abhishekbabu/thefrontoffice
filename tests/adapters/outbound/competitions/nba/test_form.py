"""Tests for basketball's recent form, read from Sleeper: `nba/form.py`.

The rules that make the numbers mean anything: percentages summed rather than
averaged, a window withheld until it can be filled, and a game nobody played
kept out of the average.
"""

from dataclasses import replace
from typing import Any

import pytest
from support.nba import FakeSleeperNBA

from thefrontoffice.adapters.outbound.competitions.nba.form import (
    MIN_FORM_GAMES,
    RECENT_GAMES,
    SleeperNBAForm,
    nine_cat,
)
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta


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
    assert set(stats) == {"last_5", "recent", "minutes"}


def test_every_window_appears_once_there_are_enough_games() -> None:
    stats = _form(logs=_run(20)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"last_5", "last_10", "last_15", "recent", "minutes"}


def test_the_recent_run_is_every_game_while_short_of_fifteen() -> None:
    """Week five, most players have twelve-odd games; leaving them blank until
    fifteen hid the form of nearly every roster."""
    logs = {"p1": [_game(f"2026-01-{i + 1:02d}", pts=10 + i) for i in range(12)]}

    stats = _form(logs=logs).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert stats["recent"].games == 12
    assert stats["recent"].line["PTS"] == pytest.approx(sum(range(10, 22)) / 12)


def test_the_recent_run_stops_at_the_last_fifteen() -> None:
    logs = {"p1": [_game(f"2026-01-{i + 1:02d}", pts=20 if i < RECENT_GAMES else 0) for i in range(20)]}

    stats = _form(logs=logs).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert stats["recent"] == (RECENT_GAMES, stats["last_15"])
    assert stats["recent"].line["PTS"] == 20.0


def test_a_player_under_the_minimum_games_carries_no_form() -> None:
    """One or two games is a single night reported as a rate."""
    assert _form(logs=_run(MIN_FORM_GAMES - 1)).get_player_stats("Nikola Jokic") is None


def test_the_minimum_games_is_enough_for_a_recent_run() -> None:
    stats = _form(logs=_run(MIN_FORM_GAMES)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"recent", "minutes"}


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


def test_the_box_scores_carry_every_game_and_find_a_player_by_name() -> None:
    logs = _run(3)

    scores = _form(logs=logs).box_scores()

    assert scores.logs == logs
    assert scores.players["p1"].name == "Nikola Jokic"
    assert scores.index.lookup("Nikola Jokic") == "p1"


def test_box_scores_that_will_not_load_are_empty() -> None:
    scores = _form(error=SleeperAPIError("down")).box_scores()

    assert (dict(scores.logs), dict(scores.players), scores.index.lookup("Nikola Jokic")) == ({}, {}, None)


def test_his_minutes_are_kept_game_by_game_newest_first() -> None:
    """How steady his role is: no category scores them, but his worth reads them."""
    logs = {"p1": [replace(_game(f"2026-01-0{i}", pts=10), minutes=float(30 + i)) for i in (3, 2, 1)]}

    stats = _form(logs=logs).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert stats["minutes"] == (33.0, 32.0, 31.0)
