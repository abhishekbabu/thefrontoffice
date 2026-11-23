"""Tests for a basketball week as the simulation reads it: `competitions/nba/forecast.py`."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.forecast import (
    Week,
    active_slots,
    board,
    categories,
    points,
    starts,
)
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    FIELD_GOALS,
    POINTS,
    TURNOVERS,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    MatchupSide,
    Pairing,
    StatCategory,
    YahooPlayer,
)
from thefrontoffice.domain.errors import UnsupportedError

NIGHTS = ("2026-02-12", "2026-02-13", "2026-02-14")


def _night(day: str, home: str = "DEN", away: str = "LAL") -> ScheduledGame:
    return ScheduledGame(week=1, date=day, home=home, away=away, status="pre_game")


def _game(**stats: float) -> NBAGameLog:
    return NBAGameLog(player_id="p", date="2026-02-01", opponent="BOS", stats=stats)


def _week(
    logs: Mapping[str, list[NBAGameLog]] | None = None,
    *,
    left: tuple[ScheduledGame, ...] = tuple(_night(day) for day in NIGHTS),
    returns: Mapping[str, date] | None = None,
    weekly: bool = False,
) -> Week:
    found = logs or {}
    return Week(games=lambda p: found.get(p.name, []), left=left, returns=returns or {}, weekly=weekly, seed=1)


def _counts(
    roster: list[YahooPlayer], week: Week, slots: int, worth: Mapping[str, float] | None = None
) -> dict[str, int]:
    return starts(roster, week, slots, worth or {})


# ── who plays which games ───────────────────────────────────────────────


def test_every_player_whose_club_plays_starts_each_of_its_games_while_there_are_slots() -> None:
    roster = [make_player("A", team="DEN", selected_position="C"), make_player("B", team="BOS", selected_position="PG")]

    assert _counts(roster, _week(), slots=2) == {"a": 3}


def test_on_a_crowded_night_only_the_best_the_slots_hold_start() -> None:
    roster = [
        make_player("Star", team="DEN", selected_position="C"),
        make_player("Role", team="LAL", selected_position="BN"),
    ]

    counts = _counts(roster, _week(), slots=1, worth={"star": 40.0, "role": 15.0})

    assert counts == {"star": 3}


def test_on_a_night_the_leagues_slots_seat_only_who_fits_them() -> None:
    """One C slot and one PG: the better centre starts, and the guard beside him, never a second centre."""
    roster = [
        make_player("Big", position="C", team="DEN", selected_position="C"),
        make_player("Other Big", position="C", team="LAL", selected_position="BN"),
        make_player("Guard", position="PG", team="LAL", selected_position="PG"),
    ]
    week = replace(_week(), lineup=("C", "PG"))

    counts = _counts(roster, week, slots=3, worth={"big": 30.0, "other-big": 25.0, "guard": 10.0})

    assert counts == {"big": 3, "guard": 3}
    assert _counts(roster, _week(), slots=3) == {"big": 3, "other-big": 3, "guard": 3}


def test_nobody_on_an_injured_slot_plays() -> None:
    roster = [make_player("A", team="DEN", selected_position="IL", status="O")]

    assert _counts(roster, _week(), slots=10) == {}


def test_a_player_ruled_out_plays_from_the_day_he_is_expected_back() -> None:
    hurt = make_player("A", team="DEN", selected_position="C", status="O")
    unknown = make_player("B", team="LAL", selected_position="PF", status="INJ")

    counts = _counts([hurt, unknown], _week(returns={"a": date(2026, 2, 13)}), slots=10)

    assert counts == {"a": 2}


def test_a_day_to_day_player_plays() -> None:
    assert _counts([make_player("A", team="DEN", selected_position="C", status="GTD")], _week(), slots=1) == {"a": 3}


def test_where_lineups_are_set_for_the_week_todays_starters_play_every_game_and_the_bench_none() -> None:
    roster = [
        make_player("Starter", team="DEN", selected_position="C"),
        make_player("Other", team="LAL", selected_position="PF"),
        make_player("Bench", team="LAL", selected_position="BN"),
    ]

    counts = _counts(roster, _week(weekly=True), slots=1)

    assert counts == {"starter": 3, "other": 3}


def test_where_no_roster_fills_a_slot_today_everyone_who_plays_counts() -> None:
    roster = [make_player("A", team="DEN"), make_player("B", team="LAL")]

    assert _counts(roster, _week(), slots=0) == {"a": 3, "b": 3}


def test_a_game_with_no_readable_date_is_no_night() -> None:
    assert _counts([make_player("A", team="DEN", selected_position="C")], _week(left=(_night("TBD"),)), slots=1) == {}


def test_a_side_starts_as_many_as_the_fuller_lineup_holds() -> None:
    mine = [make_player("A", selected_position="PG"), make_player("B", selected_position="BN")]
    theirs = [make_player("C", selected_position="PG"), make_player("D", selected_position="C")]
    theirs.append(make_player("E", selected_position="IL"))

    assert active_slots(mine, theirs) == 2


# ── what is on the board ────────────────────────────────────────────────


def test_the_board_reads_counts_and_a_percentages_makes_over_attempts() -> None:
    side = MatchupSide("t.1", "Mine", "5", {"9004003": "109/218", "5": ".500", "12": "279", "19": "-"})

    totals = board(side, [FIELD_GOALS, POINTS, TURNOVERS], ("fgm", "fga", "pts", "to"))

    assert totals == (109.0, 218.0, 279.0, 0.0)


# ── a category week ─────────────────────────────────────────────────────

NINE = [StatCategory(c.yahoo_stat, c.label, fewer_wins=c is TURNOVERS) for c in CATEGORIES]


def _pairing(
    mine: dict[str, str] | None = None, theirs: dict[str, str] | None = None, *, scored: tuple[str, str] = ("", "")
) -> Pairing:
    return Pairing(
        start=date(2026, 2, 9),
        end=date(2026, 2, 15),
        mine=MatchupSide("t.1", "Mine", scored[0], mine or {}),
        opponent=MatchupSide("t.2", "Theirs", scored[1], theirs or {}),
    )


def test_a_category_week_lists_each_scored_category_with_its_direction_and_how_it_compares() -> None:
    matchup = categories(_pairing(), [], [], _week(), NINE).categories

    assert matchup is not None
    named = {c.name: c for c in matchup.categories}
    assert list(named) == [c.label for c in CATEGORIES]
    assert (named["FG%"].made, named["FG%"].attempts, named["FG%"].places) == ("fgm", "fga", 3)
    assert (named["TO"].fewer_wins, named["PTS"].places) == (True, None)


def test_each_player_brings_his_recent_box_scores_and_the_games_he_would_start() -> None:
    star = make_player("Star", team="DEN", key="s", selected_position="C")
    unmatched = make_player("Nobody", team="DEN", key="n", selected_position="PG")
    logs = {"Star": [_game(pts=30, fgm=11, fga=20), _game(pts=20, fgm=8, fga=18)]}

    matchup = categories(_pairing({"12": "40"}), [star, unmatched], [], _week(logs), NINE).categories

    assert matchup is not None
    (line,) = matchup.mine
    by_stat = dict(zip(matchup.stats, line.samples[0], strict=True))
    assert (line.player_id, line.games, len(line.samples)) == ("s", 3, 2)
    assert (by_stat["pts"], by_stat["fgm"], by_stat["fga"], by_stat["reb"]) == (30.0, 11.0, 20.0, 0.0)
    assert dict(zip(matchup.stats, matchup.board_mine, strict=True))["pts"] == 40.0
    assert matchup.theirs == ()


def test_a_league_scoring_a_category_no_box_score_here_builds_is_not_forecast() -> None:
    doubles = [*NINE, StatCategory("27", "DD")]

    with pytest.raises(UnsupportedError, match="DD"):
        categories(_pairing(), [], [], _week(), doubles)


# ── a points week ───────────────────────────────────────────────────────

WEIGHTS = {"12": 1.0, "15": 1.2, "19": -1.0}


def test_a_points_week_is_whats_on_the_board_plus_each_starters_games_in_fantasy_points() -> None:
    star = make_player("Star", team="DEN", key="s", selected_position="C")
    logs = {"Star": [_game(pts=20, reb=10, to=2), _game(pts=10, reb=5, to=0)]}

    matchup = points(_pairing(scored=("744.3", "683.4")), [star], [], _week(logs), WEIGHTS)

    board_mine, player = matchup.mine
    assert (board_mine.floor, board_mine.games, board_mine.samples) == (744.3, 0, ())
    assert (player.player_id, player.games, player.samples) == ("s", 3, (30.0, 16.0))
    assert player.projection == pytest.approx(69.0)
    assert [o.floor for o in matchup.theirs] == [683.4]
    assert matchup.seed == 1


def test_a_points_league_weighting_a_stat_no_box_score_here_counts_is_not_forecast() -> None:
    star = make_player("Star", team="DEN", selected_position="C")

    with pytest.raises(UnsupportedError):
        points(_pairing(), [star], [], _week({"Star": [_game(pts=20)]}), {"9004003": 1.0})
