"""Tests for football's shared facts: `competitions/nfl/rules.py`."""

from dataclasses import replace

from thefrontoffice.adapters.outbound.competitions.nfl.rules import (
    FANTASY_POSITIONS,
    FLEX_ELIGIBILITY,
    SCORING_LABELS,
    SEASON_WEEKS,
    last_regular_week,
    playoff_round,
    scoring_name,
    season_end,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import STARTING_SLOTS, SleeperLeague

LEAGUE = SleeperLeague(
    league_id="L1", name="L", season="2026", total_rosters=12, scoring_format="pts_ppr", playoff_week_start=15
)


def test_every_scoring_slot_sleeper_lists_is_a_position_or_a_flex_the_rules_know() -> None:
    """The platform cannot import the competition, so the two lists are kept
    in step here: a slot Sleeper scores that the rules do not know would be
    filled by no one, and a position the rules score that Sleeper never
    starts would never reach a lineup."""
    assert set(STARTING_SLOTS) == FANTASY_POSITIONS | FLEX_ELIGIBILITY.keys()


def test_a_flex_slot_accepts_only_positions_the_league_scores() -> None:
    for slot, positions in FLEX_ELIGIBILITY.items():
        assert set(positions) <= FANTASY_POSITIONS, slot


def test_every_scoring_format_has_a_short_name_for_the_header() -> None:
    assert all(scoring_name(scoring) for scoring in SCORING_LABELS)


# ── the season's weeks ──────────────────────────────────────────────────


def test_six_teams_play_three_one_week_rounds_through_week_17() -> None:
    league = replace(LEAGUE, playoff_teams=6)

    assert (last_regular_week(league), season_end(league)) == (14, 17)


def test_a_two_week_final_ends_the_season_a_week_later() -> None:
    assert season_end(replace(LEAGUE, playoff_week_start=14, playoff_teams=6, playoff_round_type=1)) == 17


def test_two_week_rounds_double_the_bracket_but_never_run_past_the_nfls_last_week() -> None:
    assert season_end(replace(LEAGUE, playoff_week_start=12, playoff_teams=4, playoff_round_type=2)) == 15
    assert season_end(replace(LEAGUE, playoff_teams=6, playoff_round_type=2)) == SEASON_WEEKS


def test_a_league_with_no_bracket_runs_to_the_nfls_last_week() -> None:
    assert season_end(replace(LEAGUE, playoff_week_start=0, playoff_teams=6)) == SEASON_WEEKS
    assert season_end(LEAGUE) == SEASON_WEEKS
    assert last_regular_week(replace(LEAGUE, playoff_week_start=0)) == SEASON_WEEKS


# ── the bracket's rounds ────────────────────────────────────────────────
# How a bracket is sized and its rounds named is shared (`competitions/test_brackets.py`);
# these cover Sleeper's round-type codes and the season's bounds.


def _rounds(teams: int, round_type: int = 0, start: int = 14) -> dict[int, str]:
    """Every bracket week the league plays, with the round it names."""
    league = replace(LEAGUE, playoff_week_start=start, playoff_teams=teams, playoff_round_type=round_type)
    return {week: playoff_round(league, week) for week in range(start, season_end(league) + 1)}


def test_a_two_week_final_spans_two_weeks_and_says_which() -> None:
    """The live league: six teams from week 14 — three rounds, not four."""
    assert _rounds(6, round_type=1) == {
        14: "Quarterfinals",
        15: "Semifinals",
        16: "Final, week 1 of 2",
        17: "Final, week 2 of 2",
    }


def test_two_week_rounds_label_every_week_of_every_round() -> None:
    assert _rounds(8, round_type=2, start=12) == {
        12: "Quarterfinals, week 1 of 2",
        13: "Quarterfinals, week 2 of 2",
        14: "Semifinals, week 1 of 2",
        15: "Semifinals, week 2 of 2",
        16: "Final, week 1 of 2",
        17: "Final, week 2 of 2",
    }


def test_the_last_week_season_end_counts_is_the_finals() -> None:
    for teams in (4, 6, 8, 12):
        for round_type in (0, 1, 2):
            rounds = _rounds(teams, round_type, start=12)
            assert rounds[max(rounds)].startswith("Final"), (teams, round_type)


def test_regular_season_weeks_and_weeks_past_the_final_name_no_round() -> None:
    league = replace(LEAGUE, playoff_week_start=14, playoff_teams=4)

    assert (playoff_round(league, 13), playoff_round(league, 16)) == ("", "")
    assert playoff_round(replace(LEAGUE, playoff_week_start=0, playoff_teams=6), 16) == ""


def test_a_league_that_names_no_bracket_size_calls_its_playoff_weeks_playoffs() -> None:
    assert playoff_round(replace(LEAGUE, playoff_week_start=15, playoff_teams=0), 16) == "Playoffs"
