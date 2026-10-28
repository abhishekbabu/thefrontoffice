"""Tests for the league beyond this week.

Covers `nfl/league.py`: the season, the table, the real games, the activity.
"""

from dataclasses import replace

import pytest
from support.nfl import DEFAULT_PROJECTIONS, FakeSleeper, at_week, game_line, league_client, nfl_provider, proj

from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    Transaction,
)

# ── the league beyond this week ─────────────────────────────────────────


def test_the_leagues_header_is_the_season_so_far() -> None:
    """Record and points for answer how the season is going, which is this view's question."""
    season = {
        stat.label: stat.value
        for stat in nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).schedule("L1").headline
    }

    assert (season["Record"], season["Points for"], season["Place"]) == ("2-1", "250.5", "1st of 1")


def test_the_season_spans_every_regular_season_week() -> None:
    season = nfl_provider(league_client()).schedule("L1").season
    assert [row.label for row in season[:3]] == ["Week 1", "Week 2", "Week 3"]
    assert len(season) == 18


def test_a_week_carries_the_days_it_is_actually_played() -> None:
    """An NFL week runs Thursday to Monday, so one date is wrong for most of it."""
    season = nfl_provider(league_client()).schedule("L1").season
    assert season[0].date == "10-14 Sep"


def test_a_future_week_has_no_score() -> None:
    """A week that has not happened is not nil-nil."""
    season = nfl_provider(league_client()).schedule("L1").season
    assert season[5].result == ""
    assert season[5].tone == "neutral"


def test_a_played_week_carries_its_score_and_whether_it_was_won() -> None:
    season = nfl_provider(at_week(5)).schedule("L1").season

    assert season[0].result == "88.5-96.1"
    assert season[0].tone == "warning"  # 88.5 lost


def test_the_current_week_is_marked() -> None:
    season = nfl_provider(league_client()).schedule("L1").season
    assert [row.label for row in season if row.is_current] == ["Week 3"]


def test_the_table_is_sorted_on_the_record_and_says_which_is_yours() -> None:
    standings = nfl_provider(league_client()).schedule("L1").standings
    assert [row.rank for row in standings] == [1, 2]
    assert standings[0].record == "3-0"  # the 3-win roster leads
    assert [row.is_mine for row in standings] == [False, True]


def test_the_real_games_behind_the_week_are_listed_with_their_day() -> None:
    matches = nfl_provider(at_week(2)).schedule("L1").matches
    assert [(m.away, m.home) for m in matches] == [("BUF", "MIA")]
    assert matches[0].label == "Thu 17 Sep"


def test_a_week_with_no_real_games_lists_none() -> None:
    """The default fake season only reaches week 2."""
    assert nfl_provider(league_client()).schedule("L1").matches == []


def test_a_game_you_have_players_in_is_marked() -> None:
    """The only thing that makes one game on a slate different from another."""
    matches = nfl_provider(at_week(2)).schedule("L1").matches
    marked = {(m.away, m.home) for m in matches if m.detail}

    assert marked == {("BUF", "MIA")}  # every fake projection is a BUF player


def test_activity_is_newest_first_on_the_instant_not_the_label() -> None:
    """ "Sep 3" sorts before "Sep 21" alphabetically and after it in time."""
    client = at_week(
        2,
        transactions={
            1: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={}, when=1_756_000_000_000)],
            2: [Transaction(kind="trade", roster_ids=[2], adds={}, drops={"rb2": 2}, when=1_759_000_000_000)],
        },
    )

    activity = nfl_provider(client).schedule("L1").activity

    assert [row.what for row in activity] == ["Trade", "Waiver"]


def test_activity_names_players_rather_than_identifiers() -> None:
    client = league_client(
        transactions={3: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={"rb1": 1}, when=1)]}
    )

    activity = nfl_provider(client).schedule("L1").activity

    assert activity[0].detail == "+Star QB, -Good RB"
    assert activity[0].tone == "good"  # it was mine


def test_a_failed_activity_fetch_leaves_the_rest_of_the_page() -> None:
    schedule = nfl_provider(league_client(transactions_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.activity == []
    assert schedule.standings


def test_dates_are_enrichment_not_a_reason_to_fail() -> None:
    """A week without them is still a week."""
    schedule = nfl_provider(league_client(schedule_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.season
    assert schedule.season[0].date == ""
    assert schedule.matches == []


def test_the_season_ends_with_the_playoffs_last_round() -> None:
    """Six teams take three rounds from week 14: the NFL's week 18 is no week of this league's."""
    season = nfl_provider(_with_playoffs(7, spots=6, start=14)).schedule("L1").season

    assert season[-1].label == "Week 16"


def test_a_bracket_week_still_to_come_names_the_round_not_a_placeholder_opponent() -> None:
    """Sleeper pairs the bracket weeks like any other until the regular season ends."""
    season = nfl_provider(_with_playoffs(7, spots=6, start=14)).schedule("L1").season

    week14 = next(row for row in season if row.label == "Week 14")
    week13 = next(row for row in season if row.label == "Week 13")
    assert week14.opponent == "" and week14.detail != week13.detail
    assert (week14.playoffs, week13.playoffs) == (True, False)
    assert week13.detail == "3-0"  # the regular season keeps its opponent, and his record


# ── the rest of the season, for the simulation ──────────────────────────


def _with_playoffs(week: int, spots: int = 1, start: int = 9) -> FakeSleeper:
    from dataclasses import replace

    client = at_week(week)
    client.league = replace(client.league, playoff_teams=spots, playoff_week_start=start)
    return client


def test_the_season_left_is_every_week_up_to_the_playoffs() -> None:
    season = nfl_provider(_with_playoffs(7)).season_input("L1")

    assert season is not None
    assert [(f.week, f.home, f.away) for f in season.fixtures] == [(7, "1", "2"), (8, "1", "2")]
    assert (season.spots, season.mine, season.week) == (1, "1", 7)


def test_each_team_starts_from_its_record_and_is_scored_by_its_best_lineup() -> None:
    season = nfl_provider(_with_playoffs(7)).season_input("L1")

    assert season is not None
    assert {t.team_id: t.wins for t in season.teams} == {"1": 2, "2": 3}
    # Mine projects a QB and a RB; theirs only the weak RB, so mine is stronger in every week.
    means = {(t.team_id, t.week): t.mean for t in season.scoring}
    assert all(means[("1", w)] > means[("2", w)] for w in (7, 8))


def test_a_league_in_its_playoffs_has_no_season_left_to_simulate() -> None:
    assert nfl_provider(_with_playoffs(9)).season_input("L1") is None


def test_a_league_that_names_no_playoffs_has_none_to_reach() -> None:
    assert nfl_provider(at_week(7)).season_input("L1") is None


# ── a backup, priced by the weeks his starters will miss ────────────────


def _mine_against_theirs(client: FakeSleeper) -> float:
    """My mean over theirs in week 7: a ratio, so the league-wide rescaling cancels out."""
    season = nfl_provider(client).season_input("L1")
    assert season is not None
    means = {(t.team_id, t.week): t.mean for t in season.scoring}
    return means[("1", 7)] / means[("2", 7)]


def _with_backup_qb(client: FakeSleeper, backup: bool) -> FakeSleeper:
    """My roster with or without a second quarterback, whom no healthy lineup of mine starts."""
    client.projections = {**DEFAULT_PROJECTIONS, "qb2": proj("qb2", "Spare QB", "QB", 15.0)}
    if backup:
        client.rosters[0] = replace(client.rosters[0], player_ids=[*client.rosters[0].player_ids, "qb2"])
    return client


def test_a_backup_raises_what_a_roster_is_expected_to_score() -> None:
    """Before the league has played enough to measure it, starters miss weeks at the default rate."""
    with_backup = _mine_against_theirs(_with_backup_qb(_with_playoffs(7), backup=True))
    without = _mine_against_theirs(_with_backup_qb(_with_playoffs(7), backup=False))

    assert with_backup > without


def test_a_backup_is_still_priced_when_the_game_lines_are_down() -> None:
    def down(backup: bool) -> float:
        client = _with_backup_qb(_with_playoffs(7), backup=backup)
        client.game_lines_error = SleeperAPIError("down")
        return _mine_against_theirs(client)

    assert down(backup=True) > down(backup=False)


def _every_regular_plays_every_week(client: FakeSleeper) -> FakeSleeper:
    """Forty regulars who never miss a game: chances enough for the league's own rate, and it is nought."""
    client.game_lines = [
        game_line(f"wr{n}", week, off_snp=50, tm_off_snp=60) for n in range(40) for week in range(1, 7)
    ]
    return client


def test_in_a_league_whose_regulars_never_miss_a_backup_adds_nothing() -> None:
    with_backup = _mine_against_theirs(_every_regular_plays_every_week(_with_backup_qb(_with_playoffs(7), True)))
    without = _mine_against_theirs(_every_regular_plays_every_week(_with_backup_qb(_with_playoffs(7), False)))

    assert with_backup == pytest.approx(without)
