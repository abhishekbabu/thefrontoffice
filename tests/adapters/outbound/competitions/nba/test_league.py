"""Tests for the basketball table and season: `nba/league.py`."""

from dataclasses import replace
from datetime import date, datetime

import pytest

from thefrontoffice.adapters.outbound.competitions.nba.league import season, season_year, table, week_dates
from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    LeagueSettings,
    MatchupSide,
    Pairing,
    TeamStanding,
    YahooTeam,
)

RULES = LeagueSettings(playoff_start_week=19, playoff_teams=6)
RECORDS = {"t.2": "3-1"}


def _week(
    mine: str = "",
    theirs: str = "",
    *,
    status: str = "",
    winner: str = "",
    tied: bool = False,
    tied_categories: int = 0,
    playoffs: bool = False,
    consolation: bool = False,
) -> Pairing:
    return Pairing(
        start=date(2026, 11, 16),
        end=date(2026, 11, 22),
        mine=MatchupSide(team_key="t.1", name="Mine", points=mine, stats={}),
        opponent=MatchupSide(team_key="t.2", name="Theirs", points=theirs, stats={}),
        status=status,
        winner=winner,
        tied=tied,
        tied_categories=tied_categories,
        playoffs=playoffs,
        consolation=consolation,
    )


def _team(key: str, rank: int, *, seed: int = 0, faab: str = "", waiver: int = 0) -> YahooTeam:
    return YahooTeam(
        team_key=key,
        name=key,
        faab_balance=faab,
        waiver_priority=waiver,
        standing=TeamStanding(
            rank=rank, wins=5, losses=1, ties=0, points_for="61", points_against="40", playoff_seed=seed
        ),
    )


# ── the table ───────────────────────────────────────────────────────────


def test_the_table_is_in_rank_order_with_yours_marked_by_key() -> None:
    rows = table([_team("t.2", 2), _team("t.1", 1)], mine="t.2")

    assert [(row.team_id, row.rank, row.is_mine) for row in rows] == [("t.1", 1, False), ("t.2", 2, True)]
    assert (rows[0].record, rows[0].points, rows[0].points_against) == ("5-1", "61", "40")


def test_waiver_budget_and_order_show_only_where_the_league_has_them() -> None:
    with_faab, without = table([_team("t.1", 1, faab="73", waiver=4), _team("t.2", 2)], mine="t.1")

    assert (with_faab.waiver_budget, with_faab.waiver_order) == ("$73", "4")
    assert (without.waiver_budget, without.waiver_order) == ("", "")


def test_the_seed_shows_only_once_it_differs_from_the_place() -> None:
    reseeded, seeded = table([_team("t.1", 1, seed=3), _team("t.2", 2, seed=2)], mine="t.1")

    assert (reseeded.detail, seeded.detail) == ("Seed 3", "")


def test_a_team_without_standings_has_no_row() -> None:
    assert table([YahooTeam(team_key="t.9", name="Half-loaded")], mine="t.9") == []


# ── the season ──────────────────────────────────────────────────────────


def test_a_settled_category_week_reads_won_lost_tied_and_who_won() -> None:
    (row,) = season(
        {3: _week("5", "3", status="postevent", winner="t.1", tied_categories=1)}, RULES, 5, RECORDS, points=False
    )

    assert (row.label, row.date, row.opponent, row.detail) == ("Week 3", "16-22 Nov", "Theirs", "3-1")
    assert (row.result, row.outcome, row.playoffs) == ("5-3-1", "won", False)


def test_a_points_week_reads_the_points() -> None:
    (row,) = season({3: _week("1023.5", "998", status="postevent", winner="t.2")}, RULES, 5, RECORDS, points=True)

    assert (row.result, row.outcome) == ("1023.5-998", "lost")


def test_a_tied_week_is_drawn() -> None:
    (row,) = season(
        {3: _week("4", "4", status="postevent", tied=True, tied_categories=1)}, RULES, 5, RECORDS, points=False
    )

    assert (row.result, row.outcome) == ("4-4-1", "drawn")


def test_the_week_being_played_has_the_score_so_far_and_no_outcome() -> None:
    weeks = {5: _week("6", "3", status="midevent", winner="t.1"), 6: _week("0", "0", status="preevent")}

    current, upcoming = season(weeks, RULES, 5, RECORDS, points=False)

    assert (current.result, current.outcome, current.is_current) == ("6-3", None, True)
    assert (upcoming.result, upcoming.outcome, upcoming.is_current) == ("", None, False)


def test_nothing_on_the_board_yet_is_no_score_rather_than_nil_all() -> None:
    weeks = {5: _week("0", "0", status="midevent")}

    assert season(weeks, RULES, 5, RECORDS, points=False)[0].result == ""
    assert season(weeks, RULES, 5, RECORDS, points=True)[0].result == ""


def test_a_regular_season_week_without_a_matchup_is_a_bye() -> None:
    (row,) = season({4: None}, RULES, 5, RECORDS, points=False)

    assert (row.opponent, row.detail, row.result, row.outcome) == ("", "bye", "", None)


def test_playoff_weeks_are_named_from_the_bracket_even_before_it_is_drawn() -> None:
    rows = season({18: None, 19: None, 20: None, 21: None}, RULES, 5, RECORDS, points=False)

    assert [(row.detail, row.playoffs) for row in rows] == [
        ("bye", False),
        ("Quarterfinals", True),
        ("Semifinals", True),
        ("Final", True),
    ]


def test_a_playoff_week_outside_the_championship_is_consolation() -> None:
    (row,) = season({20: _week(consolation=True, playoffs=True)}, RULES, 21, RECORDS, points=False)

    assert (row.opponent, row.detail, row.playoffs) == ("Theirs", "Consolation", True)


def test_a_week_past_the_final_is_still_the_playoffs() -> None:
    rules = replace(RULES, playoff_teams=2)

    assert [row.detail for row in season({19: None, 20: None}, rules, 5, RECORDS, points=False)] == [
        "Final",
        "Playoffs",
    ]


def test_a_league_without_playoffs_has_no_bracket_weeks() -> None:
    rows = season({20: None}, replace(RULES, playoff_start_week=0, playoff_teams=0), 5, RECORDS, points=False)

    assert (rows[0].detail, rows[0].playoffs) == ("bye", False)


# ── the basketball calendar ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 20, tzinfo=PACIFIC), 2026),  # opening night
        (datetime(2026, 12, 31, tzinfo=PACIFIC), 2026),
        (datetime(2027, 1, 2, tzinfo=PACIFIC), 2026),  # January still belongs to the prior season
        (datetime(2027, 4, 15, tzinfo=PACIFIC), 2026),  # playoffs
        (datetime(2026, 9, 1, tzinfo=PACIFIC), 2026),  # September boundary, inclusive
        (datetime(2026, 8, 31, tzinfo=PACIFIC), 2025),  # the day before
    ],
)
def test_nba_season_rolls_over_in_september(when: datetime, expected: int) -> None:
    """Basketball's season starts in the autumn and runs into the next calendar year."""
    assert season_year(when) == expected


# ── the weeks' dates ────────────────────────────────────────────────────


def test_a_drawn_week_is_dated_by_its_scoreboard_and_one_not_drawn_follows_the_week_before() -> None:
    dates = week_dates({18: [_week()], 19: [], 20: []})

    assert dates[18] == (date(2026, 11, 16), date(2026, 11, 22))
    assert dates[19] == (date(2026, 11, 23), date(2026, 11, 29))
    assert dates[20] == (date(2026, 11, 30), date(2026, 12, 6))


def test_a_week_with_nothing_before_it_to_follow_has_no_dates() -> None:
    assert week_dates({19: [], 20: [_week()]}) == {20: (date(2026, 11, 16), date(2026, 11, 22))}
