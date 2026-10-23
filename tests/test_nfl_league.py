"""Tests for the league beyond this week.

Covers `nfl/league.py`: the season, the table, the real games, the activity.
"""

from conftest import (
    SLEEPER_USER_ID,
    _at_week,
    _league_client,
    _provider,
)

from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    Transaction,
)
from thefrontoffice.domain.errors import SleeperAPIError

MY_ID = SLEEPER_USER_ID


# ── the league beyond this week ─────────────────────────────────────────


def test_the_season_spans_every_regular_season_week() -> None:
    season = _provider(_league_client()).schedule("L1").season
    assert [row.label for row in season[:3]] == ["Week 1", "Week 2", "Week 3"]
    assert len(season) == 18


def test_a_week_carries_the_days_it_is_actually_played() -> None:
    """An NFL week runs Thursday to Monday, so one date is wrong for most of it."""
    season = _provider(_league_client()).schedule("L1").season
    assert season[0].date == "10-14 Sep"


def test_a_future_week_has_no_score() -> None:
    """A week that has not happened is not nil-nil."""
    season = _provider(_league_client()).schedule("L1").season
    assert season[5].result == ""
    assert season[5].tone == "neutral"


def test_a_played_week_carries_its_score_and_whether_it_was_won() -> None:
    season = _provider(_at_week(5)).schedule("L1").season

    assert season[0].result == "88.5-96.1"
    assert season[0].tone == "warning"  # 88.5 lost


def test_the_current_week_is_marked() -> None:
    season = _provider(_league_client()).schedule("L1").season
    assert [row.label for row in season if row.is_current] == ["Week 3"]


def test_the_table_is_sorted_on_the_record_and_says_which_is_yours() -> None:
    standings = _provider(_league_client()).schedule("L1").standings
    assert [row.rank for row in standings] == [1, 2]
    assert standings[0].record == "3-0"  # the 3-win roster leads
    assert [row.is_mine for row in standings] == [False, True]


def test_the_real_games_behind_the_week_are_listed_with_their_day() -> None:
    matches = _provider(_at_week(2)).schedule("L1").matches
    assert [(m.away, m.home) for m in matches] == [("BUF", "MIA")]
    assert matches[0].label == "Thu 17 Sep"


def test_a_week_with_no_real_games_lists_none() -> None:
    """The default fake season only reaches week 2."""
    assert _provider(_league_client()).schedule("L1").matches == []


def test_a_game_you_have_players_in_is_marked() -> None:
    """The only thing that makes one game on a slate different from another."""
    matches = _provider(_at_week(2)).schedule("L1").matches
    marked = {(m.away, m.home) for m in matches if m.detail}

    assert marked == {("BUF", "MIA")}  # every fake projection is a BUF player


def test_activity_is_newest_first_on_the_instant_not_the_label() -> None:
    """ "Sep 3" sorts before "Sep 21" alphabetically and after it in time."""
    client = _at_week(
        2,
        transactions={
            1: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={}, when=1_756_000_000_000)],
            2: [Transaction(kind="trade", roster_ids=[2], adds={}, drops={"rb2": 2}, when=1_759_000_000_000)],
        },
    )

    activity = _provider(client).schedule("L1").activity

    assert [row.what for row in activity] == ["Trade", "Waiver"]


def test_activity_names_players_rather_than_identifiers() -> None:
    client = _league_client(
        transactions={3: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={"rb1": 1}, when=1)]}
    )

    activity = _provider(client).schedule("L1").activity

    assert activity[0].detail == "+Star QB, -Good RB"
    assert activity[0].tone == "good"  # it was mine


def test_a_failed_activity_fetch_leaves_the_rest_of_the_page() -> None:
    schedule = _provider(_league_client(transactions_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.activity == []
    assert schedule.standings


def test_dates_are_enrichment_not_a_reason_to_fail() -> None:
    """A week without them is still a week."""
    schedule = _provider(_league_client(schedule_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.season
    assert schedule.season[0].date == ""
    assert schedule.matches == []


def test_the_week_says_when_it_is_played() -> None:
    """A week with no dates on it is a number, which is already known."""
    assert _provider(_league_client()).summary("L1").window == "Week 3"


def test_the_window_carries_the_dates_where_there_are_any() -> None:
    assert _provider(_at_week(2)).summary("L1").window == "Week 2 · 17 Sep"


# ── the rest of the season, for the simulation ──────────────────────────


def _with_playoffs(week: int, spots: int = 1, start: int = 9) -> object:
    from dataclasses import replace

    client = _at_week(week)
    client.league = replace(client.league, playoff_teams=spots, playoff_week_start=start)
    return client


def test_the_season_left_is_every_week_up_to_the_playoffs() -> None:
    season = _provider(_with_playoffs(7)).season_input("L1")  # type: ignore[arg-type]

    assert season is not None
    assert [(f.week, f.home, f.away) for f in season.fixtures] == [(7, "1", "2"), (8, "1", "2")]
    assert (season.spots, season.mine, season.week) == (1, "1", 7)


def test_each_team_starts_from_its_record_and_is_scored_by_its_best_lineup() -> None:
    season = _provider(_with_playoffs(7)).season_input("L1")  # type: ignore[arg-type]

    assert season is not None
    assert {t.team_id: t.wins for t in season.teams} == {"1": 2, "2": 3}
    # Mine projects a QB and a RB; theirs only the weak RB, so mine is stronger in every week.
    means = {(t.team_id, t.week): t.mean for t in season.scoring}
    assert all(means[("1", w)] > means[("2", w)] for w in (7, 8))


def test_a_league_in_its_playoffs_has_no_season_left_to_simulate() -> None:
    assert _provider(_with_playoffs(9)).season_input("L1") is None  # type: ignore[arg-type]


def test_a_league_that_names_no_playoffs_has_none_to_reach() -> None:
    assert _provider(_at_week(7)).season_input("L1") is None
