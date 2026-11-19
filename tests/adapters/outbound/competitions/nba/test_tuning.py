"""Tests for fitting and checking the spreads a basketball week is priced with: `nba/tuning.py`.

Seasons here are built by hand in November 2026, whose Mondays are the 2nd,
9th and 16th: clubs play Monday, Wednesday and Sunday, and each player puts up
the same line every night unless a test says otherwise.
"""

import math

import pytest
from support.nba import FakeSleeperNBA, FakeSleeperProjections, game_log

from thefrontoffice.adapters.outbound.competitions.nba import tuning
from thefrontoffice.adapters.outbound.competitions.nba.tuning import (
    NBAOddsTuning,
    PlayerWeek,
    check,
    fit,
    one_factor,
    weeks_of,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection, NBAGameLog
from thefrontoffice.domain.errors import NotFoundError

NIGHTS = (2, 4, 8, 9, 11, 15, 16, 18, 22)
"""Three complete weeks of Monday, Wednesday and Sunday games."""


def _line(pid: str, day: int, club: str, scale: float) -> NBAGameLog:
    return game_log(
        pid, day, team=club, pts=10 * scale, reb=4 * scale, ast=3 * scale, stl=scale, blk=scale, tpm=scale,
        fgm=4 * scale, fga=10 * scale, ftm=2 * scale, fta=3 * scale, to=scale,
    )  # fmt: skip


def _season(players: int = 24, nights: tuple[int, ...] = NIGHTS) -> dict[str, list[NBAGameLog]]:
    """`players` players, each on a club of his own and better than the last, who play every game."""
    return {f"p{i}": [_line(f"p{i}", d, f"C{i}", 1 + i / 10) for d in nights] for i in range(players)}


def _keys(week: list[PlayerWeek]) -> set[str]:
    return {p.key for p in week}


# ── the weeks a season is read as ───────────────────────────────────────


def test_a_week_is_read_once_its_players_have_three_games_and_only_once_it_is_over() -> None:
    """The first week has no form before it; a week cut off on its Wednesday is still being played."""
    weeks = weeks_of(_season(nights=(*NIGHTS, 23, 25)))

    assert len(weeks) == 2
    assert [len(p.nights) for p in weeks[0][:1]] == [3]


def test_a_player_who_sat_his_clubs_last_game_before_the_week_is_left_out_of_it() -> None:
    logs = _season()
    logs["p0"] = [g for g in logs["p0"] if g.date != "2026-11-15"]
    logs["mate"] = [_line("mate", d, "C0", 0.5) for d in NIGHTS]

    second = weeks_of(logs)[1]

    assert "p0" not in _keys(second) and "mate" in _keys(second)


def test_a_player_traded_during_the_week_is_left_out_of_it() -> None:
    logs = _season()
    logs["p1"] = [*logs["p1"][:-1], _line("p1", 22, "C2", 1.1)]

    assert "p1" not in _keys(weeks_of(logs)[1])


def test_a_weeks_players_are_its_best_by_their_line() -> None:
    weeks = weeks_of(_season(players=tuning.TEAMS * tuning.ROSTER + 5))

    assert len(weeks[0]) == tuning.TEAMS * tuning.ROSTER
    assert "p0" not in _keys(weeks[0])


def test_a_line_reads_sleepers_projection_from_the_week_before_beside_his_form() -> None:
    """Projected 20 points a game in the week before the third; his form is 10."""
    ahead = [GameProjection("p0", "P0", "C0", "BOS", f"2026-11-{d:02d}", {"pts": 20.0}) for d in (9, 11, 15)]
    later = [GameProjection("p0", "P0", "C0", "BOS", "2026-11-18", {"pts": 90.0})]

    third = {p.key: p for p in weeks_of(_season(), [*ahead, *later])[1]}

    assert third["p0"].line["PTS"] == pytest.approx(15.0)


# ── the fit ─────────────────────────────────────────────────────────────


def test_a_season_played_exactly_as_projected_needs_no_spread_and_keeps_every_line() -> None:
    found = fit("2026", weeks_of(_season()))

    assert found.missed == 0.0
    assert all(spread == pytest.approx(0.0, abs=1e-9) for spread in [*found.form.values(), *found.rate.values()])
    assert found.kept["PTS"] == pytest.approx(1.0)
    assert found.player_weeks == 2 * 24


def test_the_games_players_sat_out_are_the_share_missed() -> None:
    weeks = weeks_of(_season())
    sitting = [[_sat(p) if i % 2 else p for i, p in enumerate(week)] for week in weeks]

    found = fit("2026", sitting)

    assert found.missed == pytest.approx(1 / 6)


def _sat(player: PlayerWeek) -> PlayerWeek:
    """His week with its first game sat out."""
    return PlayerWeek(player.key, player.line, player.value, player.form, player.nights, player.played[1:])


def test_weeks_that_swing_beyond_their_games_fit_a_spread_and_move_together() -> None:
    """Every other week a player has a big one across the board: his counts all swing as one."""
    weeks = weeks_of(_season())
    swung = [[_scaled(p, 1.5 if i % 2 else 0.5) for i, p in enumerate(week)] for week in weeks]

    found = fit("2026", swung)

    assert found.form["PTS"] > 0.2
    assert found.correlation["PTS"]["REB"] > 0.9
    assert found.loadings["PTS"] > 0.9


def _scaled(player: PlayerWeek, by: float) -> PlayerWeek:
    played = tuple(
        NBAGameLog(g.player_id, g.date, g.opponent, {k: v * by for k, v in g.stats.items()}, g.team)
        for g in player.played
    )
    return PlayerWeek(player.key, player.line, player.value, player.form, player.nights, played)


def test_nothing_to_fit_on_is_refused() -> None:
    with pytest.raises(NotFoundError):
        fit("2026", [])


def test_one_factor_recovers_the_loadings_a_correlation_was_built_from() -> None:
    built = {"a": 0.8, "b": 0.6, "c": 0.3}
    correlation = {x: {y: 1.0 if x == y else built[x] * built[y] for y in built} for x in built}

    assert one_factor(correlation) == pytest.approx(built, abs=0.01)


# ── the check ───────────────────────────────────────────────────────────


def test_every_category_and_week_of_every_league_dealt_is_called() -> None:
    weeks = weeks_of(_season())

    checked = check("2026", "fitted", weeks, leagues=2)

    matchups = len(weeks) * 2 * tuning.TEAMS // 2
    assert (checked.matchups.matchups, checked.categories.matchups) == (matchups, matchups * 9)
    assert 0.0 <= checked.categories.brier <= 1.0


def test_the_spreads_set_by_hand_and_the_fitted_ones_call_the_same_weeks_differently() -> None:
    weeks = weeks_of(_season())

    briers = {model: check("2026", model, weeks, leagues=1).categories.brier for model in tuning.MODELS}

    assert briers["hand-set"] != briers["fitted"]


def test_nothing_to_check_on_is_refused() -> None:
    with pytest.raises(NotFoundError):
        check("2026", "fitted", [])


def test_a_level_category_is_half_won() -> None:
    weeks = weeks_of(_season(players=tuning.TEAMS))
    level = [[PlayerWeek(p.key, p.line, p.value, p.form, p.nights, ()) for p in week] for week in weeks]

    checked = check("2026", "fitted", level, leagues=1)

    assert {b.won for b in checked.matchups.buckets} == {0.5}


# ── reading seasons ─────────────────────────────────────────────────────


def test_the_season_finished_last_is_fitted_and_the_one_being_played_checked() -> None:
    reader = NBAOddsTuning(FakeSleeperNBA(), FakeSleeperProjections())

    assert reader.seasons() == ("2025", "2026")


def test_a_season_is_read_from_sleepers_box_scores_and_projections() -> None:
    reader = NBAOddsTuning(FakeSleeperNBA(logs=_season()), FakeSleeperProjections())

    found = reader.fit_odds("2026")
    checked = reader.check_odds("2025", "hand-set")

    assert found.player_weeks == 48
    assert checked.weeks == 2 and math.isfinite(checked.matchups.brier)
