"""Tests for basketball's recent form, read from Sleeper: `nba/form.py`.

The rules that make the numbers mean anything: percentages summed rather than
averaged, a window withheld until it can be filled, and a game nobody played
kept out of the average.
"""

from dataclasses import replace
from typing import Any

import pytest
from support.nba import FakeSleeperNBA

from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nba.form import (
    MIN_FORM_GAMES,
    RECENT_GAMES,
    ROLE_GAMES,
    BoxScores,
    SleeperNBAForm,
    availability,
    missed,
    nine_cat,
)
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, PlayerMeta


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


def test_the_line_is_keyed_by_every_category_label() -> None:
    """The drawer and the prompt read the line by these labels; a key spelled any
    other way is a figure nobody finds."""
    line = nine_cat([_game("2026-01-01", pts=2, fgm=1, fga=2, ftm=1, fta=1)])

    assert set(line) == {c.label for c in CATEGORIES} | {c.attempted for c in CATEGORIES if c.is_percentage}


# ── the windows ─────────────────────────────────────────────────────────


def _run(n: int) -> dict[str, list[NBAGameLog]]:
    return {"p1": [_game(f"2026-01-{i + 1:02d}", pts=10) for i in range(n)]}


def test_a_window_is_reported_only_once_it_can_be_filled() -> None:
    """Five games averaged into a "last fifteen" is a different number wearing
    the same label."""
    stats = _form(logs=_run(7)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"last_5", "recent", "minutes", "role", "run"}


def test_every_window_appears_once_there_are_enough_games() -> None:
    stats = _form(logs=_run(20)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert set(stats) == {"last_5", "last_10", "last_15", "recent", "minutes", "role", "run"}


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


def test_a_role_is_his_last_five_games_minutes_beside_the_whole_windows() -> None:
    """The drawer's 'last 5 · last 6 wks', so the wire's trend and the drawer read alike."""
    logs = {"p1": [replace(_game(f"2026-01-{20 - i:02d}"), minutes=38.0 if i < 5 else 30.0) for i in range(10)]}

    stats = _form(logs=logs).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert stats["role"] == (ROLE_GAMES, 38.0, 34.0)


def test_no_role_is_read_without_games_before_the_last_five() -> None:
    """With nothing to compare them against, five games are the window, not a move within it."""
    stats = _form(logs=_run(ROLE_GAMES)).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert "role" not in stats


def test_every_players_season_totals_are_one_read_by_sleepers_id() -> None:
    totals = NBASeason(player_id="p1", season="2025", games=70, minutes=2100.0, totals={})

    assert _form(seasons={"2025": {"p1": totals}}).season_totals("2025") == {"p1": totals}


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


def test_a_players_recent_games_are_his_last_fifteen_box_scores_newest_first() -> None:
    games = _form(logs=_run(20)).recent_games("Nikola Jokic")

    assert len(games) == RECENT_GAMES
    assert games[0].date == "2026-01-01"


def test_a_name_that_cannot_be_matched_carries_no_games() -> None:
    assert _form(logs=_run(20)).recent_games("Someone Else Entirely") == []
    assert _form(logs=_run(20)).games("Someone Else Entirely") == []


def test_a_players_game_log_is_every_game_in_the_window_newest_first() -> None:
    games = _form(logs=_run(20)).games("Nikola Jokic")

    assert len(games) == 20
    assert games[0].date == "2026-01-01"


def test_a_players_profile_is_his_catalog_entry() -> None:
    form = _form()

    assert form.profile("Nikola Jokic") == PlayerMeta(player_id="p1", name="Nikola Jokic", position="C", team="DEN")
    assert form.profile("Someone Else Entirely") is None


def test_a_players_season_is_his_totals_from_the_seasons_read() -> None:
    totals = NBASeason(player_id="p1", season="2025", games=70, minutes=2400.0, totals={"pts": 2000.0})
    form = _form(seasons={"2025": {"p1": totals}})

    assert form.season("Nikola Jokic", "2025") == totals
    assert form.season("Nikola Jokic", "2024") is None
    assert form.season("Someone Else Entirely", "2025") is None


def test_a_season_that_will_not_load_says_so() -> None:
    client = FakeSleeperNBA()
    client.season_error = SleeperAPIError("down")

    with pytest.raises(SleeperAPIError):
        SleeperNBAForm(client=client, season="2026").season("Nikola Jokic", "2025")


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


def test_his_last_five_games_are_kept_each_as_a_line_newest_first() -> None:
    """What a streak reads game by game, not as one average."""
    logs = {"p1": [_game(f"2026-01-{20 - i:02d}", pts=float(i)) for i in range(8)]}

    stats = _form(logs=logs).get_player_stats("Nikola Jokic")

    assert stats is not None
    assert [game["PTS"] for game in stats["run"]] == [0.0, 1.0, 2.0, 3.0, 4.0]


# ── games missed ────────────────────────────────────────────────────────


def _played(player: str, team: str, *days: str) -> list[NBAGameLog]:
    return [replace(_game(day), player_id=player, team=team) for day in sorted(days, reverse=True)]


def _scores(**logs: list[NBAGameLog]) -> BoxScores:
    index: NameIndex[str] = NameIndex()
    index.add("Nikola Jokic", "p1")
    return BoxScores(logs=logs, index=index)


def test_the_games_he_missed_are_his_clubs_since_his_last() -> None:
    """Denver played twice after his last game; a Laker game the same week is not his club's."""
    scores = _scores(
        p1=_played("p1", "DEN", "2026-01-08", "2026-01-10"),
        p2=_played("p2", "DEN", "2026-01-08", "2026-01-10", "2026-01-12", "2026-01-14"),
        p3=_played("p3", "LAL", "2026-01-13"),
    )

    assert missed(scores, "Nikola Jokic") == 2


def test_a_player_who_cannot_be_placed_or_has_no_games_missed_none() -> None:
    assert missed(_scores(p2=_played("p2", "DEN", "2026-01-12")), "Nikola Jokic") == 0
    assert missed(_scores(), "Somebody Else") == 0


def _minutes(player: str, team: str, games: dict[str, float]) -> list[NBAGameLog]:
    return [
        replace(_game(day), player_id=player, team=team, minutes=m) for day, m in sorted(games.items(), reverse=True)
    ]


def test_an_absence_is_two_games_in_a_row_or_one_straight_after_a_game_he_left() -> None:
    """Caruso's shape: a 9-minute night then a game missed; later three in a row; a lone rest night is neither."""
    days = [f"2026-11-{d:02d}" for d in range(1, 11)]
    mate = _minutes("p2", "OKC", dict.fromkeys(days, 30.0))
    played = {days[0]: 20.0, days[1]: 9.0, days[3]: 20.0, days[5]: 20.0, days[9]: 20.0}  # misses 3, 5, 7-9
    scores = _scores(p1=_minutes("p1", "OKC", played), p2=mate)

    found = availability(scores, "Nikola Jokic")

    assert found is not None
    assert (found.played, found.scheduled, found.share) == (5, 10, 0.5)
    assert [(a.day, b.day) for a, b in found.spells] == [(3, 3), (7, 9)]


def test_availability_needs_a_player_it_can_place_with_games() -> None:
    assert availability(_scores(), "Nikola Jokic") is None
