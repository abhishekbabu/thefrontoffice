"""Tests for NBA projection aggregation and the Yahoo↔Sleeper name join.

The join is by name because the two platforms share no identifier, which makes
it the fragile part of the feature: a wrong match silently attributes another
player's numbers.
"""

from datetime import date

from thefrontoffice.adapters.outbound.competitions.nba.projections import (
    ProjectionIndex,
    aggregate,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection

WEEK_START, WEEK_END = date(2026, 1, 5), date(2026, 1, 11)


def game(name: str, day: str, **stats: float) -> GameProjection:
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
        team="LAL",
        opponent="BOS",
        date=day,
        stats=base,
    )


# ── name normalization ──────────────────────────────────────────────────


# ── aggregation ─────────────────────────────────────────────────────────


def test_counting_stats_are_summed_across_games() -> None:
    totals = aggregate([game("A B", "2026-01-05", pts=20), game("A B", "2026-01-07", pts=30)])
    assert totals.games == 2
    assert totals.totals["pts"] == 50.0


def test_percentages_use_totals_not_an_average_of_ratios() -> None:
    """The same rule the historical splits follow: sum makes over sum attempts."""
    totals = aggregate(
        [
            game("A B", "2026-01-05", fgm=1, fga=1),  # 100% on one attempt
            game("A B", "2026-01-07", fgm=0, fga=19),  # 0% on nineteen
        ]
    )
    assert totals.fg_pct == 0.05


def test_no_attempts_yields_no_percentage_rather_than_zero() -> None:
    """A player projected zero free throws has no FT%, which is different from 0%."""
    totals = aggregate([game("A B", "2026-01-05", ftm=0, fta=0)])
    assert totals.ft_pct is None
    assert "FT" not in totals.summary()


def test_no_games_is_an_empty_projection() -> None:
    totals = aggregate([])
    assert totals.games == 0
    assert totals.totals == {}


def test_summary_labels_three_pointers_unambiguously() -> None:
    """ "5" + "3pm" renders as "53pm", which reads as fifty-three."""
    summary = aggregate([game("A B", "2026-01-05", tpm=5)]).summary()
    assert "5tpm" in summary
    assert "53pm" not in summary


def test_summary_leads_with_the_game_count() -> None:
    summary = aggregate([game("A B", "2026-01-05"), game("A B", "2026-01-07")]).summary()
    assert summary.startswith("2G")


# ── the matchup window ──────────────────────────────────────────────────


def test_only_games_inside_the_period_are_counted() -> None:
    index = ProjectionIndex(
        [
            game("A B", "2026-01-04"),  # before
            game("A B", "2026-01-06"),  # inside
            game("A B", "2026-01-12"),  # after
        ],
        WEEK_START,
        WEEK_END,
    )
    totals = index.lookup("A B")
    assert totals is not None
    assert totals.games == 1


def test_window_bounds_are_inclusive() -> None:
    index = ProjectionIndex([game("A B", "2026-01-05"), game("A B", "2026-01-11")], WEEK_START, WEEK_END)
    totals = index.lookup("A B")
    assert totals is not None
    assert totals.games == 2


def test_an_unparseable_date_is_excluded() -> None:
    index = ProjectionIndex([game("A B", "not-a-date")], WEEK_START, WEEK_END)
    assert index.is_empty


def test_without_a_window_every_game_counts() -> None:
    index = ProjectionIndex([game("A B", "2026-01-04"), game("A B", "2026-02-20")], None, None)
    totals = index.lookup("A B")
    assert totals is not None
    assert totals.games == 2


# ── lookup ──────────────────────────────────────────────────────────────


def test_a_yahoo_spelling_matches_a_sleeper_one() -> None:
    index = ProjectionIndex([game("Luka Dončić", "2026-01-06")], WEEK_START, WEEK_END)
    assert index.lookup("Luka Doncic") is not None


def test_an_unmatched_name_gets_no_projection() -> None:
    """Better no number than someone else's."""
    index = ProjectionIndex([game("A B", "2026-01-06")], WEEK_START, WEEK_END)
    assert index.lookup("Someone Else") is None


def test_a_unique_surname_still_matches_a_differing_first_name() -> None:
    index = ProjectionIndex([game("Cameron Johnson", "2026-01-06")], WEEK_START, WEEK_END)
    assert index.lookup("Cam Johnson") is not None


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
