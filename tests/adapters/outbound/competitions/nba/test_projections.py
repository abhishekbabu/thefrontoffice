"""Tests for NBA projection aggregation and the Yahoo↔Sleeper name join.

The join is by name because the two platforms share no identifier, which makes
it the fragile part of the feature: a wrong match silently attributes another
player's numbers.
"""

from datetime import date

from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm
from thefrontoffice.adapters.outbound.competitions.nba.projections import (
    ProjectionIndex,
    aggregate,
    plausible,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection

WEEK_START, WEEK_END = date(2026, 1, 5), date(2026, 1, 11)


def ruled_out(name: str, day: str, team: str = "LAL") -> GameProjection:
    """A game Sleeper lists him in and projects nothing for."""
    return GameProjection(
        player_id=name.lower().replace(" ", "-"), name=name, team=team, opponent="BOS", date=day, stats={}
    )


def recent(games: int = 10, **figures: float) -> PlayerStats:
    """His last `games`, a game: 20 points, 5 boards, 4 assists, 2 threes unless told otherwise."""
    run = {"PTS": 20.0, "REB": 5.0, "AST": 4.0, "3PTM": 2.0, **figures}
    return PlayerStats(recent=RecentForm(games=games, line=run))


def game(name: str, day: str, team: str = "LAL", **stats: float) -> GameProjection:
    base = {
        "pts": 20.0,
        "reb": 5.0,
        "ast": 4.0,
        "stl": 1.0,
        "blk": 0.5,
        "to": 2.0,
        "tpm": 2.0,
        "fgm": 8.0,
        "fga": 16.0,
        "ftm": 4.0,
        "fta": 5.0,
    }
    base.update(stats)
    return GameProjection(
        player_id=name.lower().replace(" ", "-"),
        name=name,
        team=team,
        opponent="BOS",
        date=day,
        stats=base,
    )


# ── aggregation ─────────────────────────────────────────────────────────


def test_counting_stats_are_summed_across_games_and_read_as_totals_not_per_game() -> None:
    """A category league is won on totals, so a projection is not averaged per game."""
    totals = aggregate([game("A B", "2026-01-05", pts=20), game("A B", "2026-01-07", pts=30)])
    assert totals.games == 2
    assert (totals.totals["pts"], totals.line["PTS"]) == (50.0, 50.0)


def test_no_games_is_an_empty_projection() -> None:
    totals = aggregate([])
    assert totals.games == 0
    assert totals.totals == {}


# ── the matchup window ──────────────────────────────────────────────────


def test_only_games_inside_the_period_are_counted_its_bounds_included() -> None:
    index = ProjectionIndex(
        [
            game("A B", "2026-01-04"),  # before
            game("A B", "2026-01-05"),  # the first day
            game("A B", "2026-01-06"),  # inside
            game("A B", "2026-01-11"),  # the last day
            game("A B", "2026-01-12"),  # after
        ],
        WEEK_START,
        WEEK_END,
    )
    totals = index.lookup("A B")
    assert totals is not None
    assert totals.games == 3


def test_an_unparseable_date_is_excluded() -> None:
    index = ProjectionIndex([game("A B", "not-a-date")], WEEK_START, WEEK_END)
    assert index.is_empty


# ── lookup ──────────────────────────────────────────────────────────────


def test_an_unmatched_name_gets_no_projection() -> None:
    """Better no number than someone else's."""
    index = ProjectionIndex([game("A B", "2026-01-06")], WEEK_START, WEEK_END)
    assert index.lookup("Someone Else") is None


def test_an_ambiguous_surname_is_refused_not_guessed() -> None:
    """Two Jacksons must not resolve to whichever was indexed first."""
    index = ProjectionIndex(
        [game("Jaren Jackson", "2026-01-06"), game("Andrew Jackson", "2026-01-06")],
        WEEK_START,
        WEEK_END,
    )
    assert index.lookup("Reggie Jackson") is None
    # An exact match still works despite the shared surname.
    assert index.lookup("Jaren Jackson") is not None


def test_an_empty_index_reports_itself_empty() -> None:
    """Out of season Sleeper publishes nothing, and the scout must fall back."""
    index = ProjectionIndex([], WEEK_START, WEEK_END)
    assert index.is_empty
    assert index.lookup("A B") is None


def test_a_game_projected_nothing_is_no_game() -> None:
    totals = aggregate([game("A B", "2026-01-05", pts=20), ruled_out("A B", "2026-01-07")])
    assert (totals.games, totals.totals["pts"]) == (1, 20.0)


# ── a namesake's line ───────────────────────────────────────────────────


def test_a_player_projected_nothing_does_not_borrow_a_namesakes_line() -> None:
    """Duncan Robinson, ruled out, once read Mitchell Robinson's rebounds through their shared surname."""
    index = ProjectionIndex(
        [
            game("Mitchell Robinson", "2026-01-06", team="BOS", reb=9.5, tpm=0.06),
            ruled_out("Duncan Robinson", "2026-01-06", team="DET"),
        ],
        WEEK_START,
        WEEK_END,
    )
    assert index.lookup("Duncan Robinson", "DET") is None
    assert index.lookup("Mitchell Robinson", "BOS") is not None


def test_a_hyphenated_surname_does_not_fall_through_to_its_last_half() -> None:
    """Trayce Jackson-Davis, projected nothing, once read Anthony Davis's 21 points a game."""
    index = ProjectionIndex(
        [game("Anthony Davis", "2026-01-06", team="DAL"), ruled_out("Trayce Jackson-Davis", "2026-01-06", team="TOR")],
        WEEK_START,
        WEEK_END,
    )
    assert index.lookup("Trayce Jackson-Davis", "TOR") is None


def test_a_match_on_another_club_is_refused() -> None:
    """A player Sleeper does not list at all must not take the only other man under his surname."""
    index = ProjectionIndex([game("Anthony Davis", "2026-01-06", team="DAL")], WEEK_START, WEEK_END)
    assert index.lookup("Trayce Jackson-Davis", "TOR") is None
    assert index.lookup("Anthony Davis", "dal") is not None


def test_a_player_projected_nothing_all_week_has_no_projection_and_an_index_of_them_is_empty() -> None:
    index = ProjectionIndex([ruled_out("A B", "2026-01-06")], WEEK_START, WEEK_END)
    assert index.lookup("A B") is None
    assert (index.is_empty, len(index)) == (True, 0)


def test_two_players_under_one_name_are_neither() -> None:
    other = GameProjection(
        player_id="other", name="Jalen Smith", team="PHX", opponent="BOS", date="2026-01-06", stats={"pts": 8.0}
    )
    index = ProjectionIndex([game("Jalen Smith", "2026-01-06", team="CHI"), other], WEEK_START, WEEK_END)
    assert index.lookup("Jalen Smith") is None


# ── plausibility ────────────────────────────────────────────────────────


def test_a_projection_far_over_his_recent_scoring_is_dropped() -> None:
    """21 points a game against 3.1 over his last ten is somebody else's line."""
    index = ProjectionIndex([game("A B", "2026-01-06", pts=21.0, reb=5.0)], WEEK_START, WEEK_END)
    assert index.find("A B", "LAL", recent(PTS=3.1, REB=3.1, AST=0.5, **{"3PTM": 0.0})) is None


def test_a_shooter_projected_a_big_mans_boards_and_no_threes_is_dropped() -> None:
    projected = aggregate([game("A B", "2026-01-06", pts=8.0, reb=9.5, ast=1.0, tpm=0.06)])
    assert plausible("A B", projected, recent(PTS=17.4, REB=1.8, AST=2.1, **{"3PTM": 3.9})) is None


def test_a_projection_in_line_with_his_run_stands() -> None:
    projected = aggregate([game("A B", "2026-01-06", pts=24.0, reb=6.0, ast=5.0, tpm=2.5)])
    assert plausible("A B", projected, recent()) is projected


def test_a_small_gap_is_no_reason_to_drop_however_large_the_ratio() -> None:
    """0.3 threes against 1.0 is a cold week, not another player."""
    projected = aggregate([game("A B", "2026-01-06", tpm=1.0)])
    assert plausible("A B", projected, recent(**{"3PTM": 0.3})) is projected


def test_without_a_recent_run_the_projection_stands() -> None:
    projected = aggregate([game("A B", "2026-01-06", pts=40.0)])
    assert plausible("A B", projected, None) is projected
    assert plausible("A B", projected, PlayerStats()) is projected
