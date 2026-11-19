"""Tests for what an FPL player is worth: form beside an outlook, scaled by fixture, minutes and fitness."""

from dataclasses import replace

import pytest
from support.fpl import FakeFPL, player

from thefrontoffice.adapters.outbound.competitions.premier_league import worth
from thefrontoffice.adapters.outbound.competitions.premier_league.worth import (
    FORM_WEEKS,
    HORIZON,
    SETTLE_MATCHES,
    Record,
    difficulty,
    record,
    settled,
    valuation,
)
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, LiveStat, Player


def _home(club: str, rating: int, week: int = 5, away: str = "ZZZ") -> Fixture:
    return Fixture(event=week, home=club, away=away, home_difficulty=rating, away_difficulty=3)


def _week(found: Player, fixtures: list[Fixture]) -> float:
    """His worth for the one gameweek given, with no form and no minutes: his projection, as fixtures and fitness scale it."""
    return valuation({found.id: found}, {}, {5: fixtures}, played=0)(found)


# ── the gameweek's fixtures ─────────────────────────────────────────────


def test_an_average_fixture_leaves_the_projection_as_it_is() -> None:
    assert _week(player(1, "MID", 6.0), [_home("ARS", 3)]) == 6.0


def test_an_easy_fixture_is_worth_more_than_a_hard_one() -> None:
    mid = player(1, "MID", 6.0)

    assert _week(mid, [_home("ARS", 2)]) == pytest.approx(6.6)
    assert _week(mid, [_home("ARS", 5)]) == pytest.approx(4.8)


def test_an_unrated_fixture_counts_as_average() -> None:
    assert difficulty(0) == 1.0


def test_a_double_gameweek_counts_both_matches() -> None:
    """FPL's projection covers the gameweek, so each match is half of it — and each is scaled by its own difficulty."""
    mid = player(1, "MID", 6.0)

    assert _week(mid, [_home("ARS", 2), _home("ARS", 4, away="YYY")]) == pytest.approx(3.0 * 1.1 + 3.0 * 0.9)


def test_a_blank_gameweek_is_worth_nothing() -> None:
    assert _week(player(1, "MID", 6.0), [_home("MCI", 2)]) == 0.0


# ── fitness ─────────────────────────────────────────────────────────────


def test_a_published_doubt_scales_the_week_by_his_chance() -> None:
    assert _week(player(1, "MID", 6.0, status="d", chance_of_playing=50), [_home("ARS", 3)]) == 3.0


def test_a_player_ruled_out_is_worth_nothing_this_week_but_recovers_over_the_horizon() -> None:
    injured = player(1, "MID", 6.0, status="i", chance_of_playing=0)
    weeks = {week: [_home("ARS", 3, week=week)] for week in range(5, 5 + HORIZON)}
    value = valuation({1: injured}, {}, weeks, played=0)

    assert value(injured) == 0.0
    assert value.horizon(injured) == pytest.approx(6.0 * (0.5 + 0.75 + 0.875))


def test_a_player_gone_from_his_club_is_worth_nothing_over_the_horizon_either() -> None:
    gone = player(1, "MID", 6.0, status="u")
    weeks = {week: [_home("ARS", 3, week=week)] for week in range(5, 5 + HORIZON)}

    assert valuation({1: gone}, {}, weeks, played=0).horizon(gone) == 0.0


def test_the_horizon_adds_every_gameweek_from_the_one_decided() -> None:
    mid = player(1, "MID", 6.0)
    weeks = {5: [_home("ARS", 3, week=5)], 6: [_home("ARS", 2, week=6)], 7: [_home("MCI", 3, week=7)]}

    assert valuation({1: mid}, {}, weeks, played=0).horizon(mid) == pytest.approx(6.0 + 6.6 + 0.0)


# ── form ────────────────────────────────────────────────────────────────


def test_form_is_points_per_match_his_club_played_so_a_match_missed_counts_as_nought() -> None:
    weeks = [{1: LiveStat(points=10, minutes=90, matches=1)}, {1: LiveStat(points=0, minutes=0, matches=1)}]

    assert record(1, weeks) == Record(points=10, matches=2, minutes=90, per_match=(90.0, 0.0))


def test_recent_form_is_settled_toward_the_season() -> None:
    hot = replace(player(1, "DEF", 6.0), total_points=50)
    run = Record(points=45, matches=5, minutes=450)

    assert settled(hot, run, played=10) == pytest.approx((45 + SETTLE_MATCHES * 5.0) / (5 + SETTLE_MATCHES))


def test_without_a_run_form_is_the_season_and_without_either_none() -> None:
    mid = replace(player(1, "MID", 6.0), total_points=40)

    assert settled(mid, Record(), played=8) == 5.0
    assert settled(mid, Record(), played=0) is None
    assert settled(mid, Record(points=12, matches=2), played=0) == 6.0


def test_steady_minutes_are_worth_a_tenth_more_and_rotation_a_tenth_less() -> None:
    steady = [{1: LiveStat(points=6, minutes=90, matches=1)} for _ in range(4)]
    rotated = [{1: LiveStat(points=6, minutes=m, matches=1)} for m in (90, 20, 90, 30)]
    mid = player(1, "MID", 6.0)

    def usage(weeks: list[dict[int, LiveStat]]) -> float:
        found = valuation({1: mid}, dict(enumerate(weeks)), {5: [_home("ARS", 3)]}, played=4).of(mid)
        assert found is not None
        return found.usage

    assert usage(steady) == pytest.approx(1.1)
    assert usage(rotated) == pytest.approx(0.9)


# ── what FPL projects ───────────────────────────────────────────────────


def _striker_and_defender() -> tuple[Player, Player, dict[int, dict[int, LiveStat]]]:
    """The live case: a centre-back on a month of clean sheets beside a striker with a far better underlying record.

    FPL's `ep_next` repeats each one's form, so ranking on it captains the defender.
    """
    striker = replace(
        player(1, "FWD", 4.0, team="MCI"),
        total_points=70,
        minutes=889,
        expected_goals=7.06,
        expected_assists=0.87,
        bonus=14,
    )
    defender = replace(
        player(2, "DEF", 10.7, team="ARS"),
        total_points=57,
        minutes=731,
        expected_goals=0.64,
        expected_assists=0.04,
        bonus=7,
    )
    weeks = {
        week: {
            1: LiveStat(points=[2, 13, 6, 8, 2][i], minutes=[90, 90, 75, 90, 90][i], matches=1),
            2: LiveStat(points=[8, 12, 9, 6, 10][i], minutes=90, matches=1, defending=2 if i % 2 else 0),
        }
        for i, week in enumerate(range(6, 11))
    }
    return striker, defender, weeks


def test_a_striker_at_home_to_an_easy_side_outranks_a_defender_on_a_month_of_clean_sheets() -> None:
    striker, defender, results = _striker_and_defender()
    fixtures = {11: [_home("MCI", 2, week=11, away="FUL"), Fixture(11, "NEW", "ARS", 3, 3)]}

    value = valuation({1: striker, 2: defender}, results, fixtures, played=10)

    assert value(striker) > value(defender)


def test_a_projection_that_only_repeats_form_is_not_counted_and_one_that_differs_is() -> None:
    striker, _, results = _striker_and_defender()
    fixtures = {11: [_home("MCI", 2, week=11)]}

    def week(found: Player) -> float:
        return valuation({1: found}, results, fixtures, played=10)(found)

    assert week(replace(striker, expected_points=9.0, form=9.0)) == week(striker)
    assert week(replace(striker, expected_points=9.0)) > week(striker)


def test_underlying_numbers_need_minutes_to_say_anything() -> None:
    assert worth.underlying(player(1, "FWD", 5.0), Record(), None, 3) is None


def test_a_defenders_clean_sheet_odds_fall_with_the_fixture() -> None:
    back = player(1, "DEF", 5.0)

    easy = worth.underlying(back, Record(), 1.0, 1)
    hard = worth.underlying(back, Record(), 1.0, 5)
    assert easy is not None and hard is not None
    assert easy - hard == pytest.approx((0.5 - 0.12) * 4)


# ── gathering ───────────────────────────────────────────────────────────


def test_form_is_read_from_the_last_finished_gameweeks_only() -> None:
    fake = FakeFPL(upcoming=11, finished=10)

    worth.gather(fake, fake.upcoming_gameweek())

    assert fake.results_requests == [list(range(11 - FORM_WEEKS, 11))]


def test_before_any_gameweek_is_over_nothing_is_asked_for_form() -> None:
    fake = FakeFPL()

    worth.gather(fake, fake.upcoming_gameweek())

    assert fake.results_requests == []


def test_results_that_will_not_load_leave_the_projection_to_value_on() -> None:
    fake = FakeFPL(upcoming=11, finished=10, results_error=FPLAPIError("down"))
    value = worth.gather(fake, fake.upcoming_gameweek())

    assert value(fake.get_players()[8]) > 0


def test_the_fixtures_it_was_figured_on_are_kept_for_every_gameweek_of_the_horizon() -> None:
    fake = FakeFPL()

    assert list(worth.gather(fake, fake.upcoming_gameweek()).weeks) == list(range(5, 5 + HORIZON))


def test_a_player_it_never_valued_is_worth_nothing() -> None:
    empty = valuation({}, {}, {5: []}, played=0)

    assert empty(player(1, "MID", 6.0)) == 0.0
    assert empty.horizon(player(1, "MID", 6.0)) == 0.0
    assert empty.of(player(1, "MID", 6.0)) is None


def test_a_match_he_plays_is_worth_the_week_over_its_matches_and_his_chance() -> None:
    doubtful = player(1, "MID", 6.0, status="d", chance_of_playing=50)
    found = valuation({1: doubtful}, {}, {5: [_home("ARS", 3), _home("ARS", 3, away="YYY")]}, played=0).of(doubtful)
    blank = valuation({1: doubtful}, {}, {5: []}, played=0).of(doubtful)

    assert found is not None and found.per_match == pytest.approx(3.0)
    assert blank is not None and blank.per_match is None
