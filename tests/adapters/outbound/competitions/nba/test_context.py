"""Tests for PlayerContextBuilder — the prompt lines both engines share."""

from datetime import date
from typing import Any

from support.nba import FakeNBA, make_player

from thefrontoffice.adapters.outbound.competitions.nba.context import PlayerContextBuilder
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import Line
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection

START, END = date(2026, 2, 9), date(2026, 2, 15)


def _stats(**overrides: float) -> Line:
    """A player's averages over a window, keyed by category label."""
    return {
        "PTS": 20.0,
        "REB": 10.0,
        "AST": 5.0,
        "STL": 1.0,
        "BLK": 2.0,
        "3PTM": 2.0,
        "FG%": 0.523,
        "FT%": 0.781,
        "TO": 3.0,
        **overrides,
    }


def _builder(stats: dict[str, Any] | None = None, games: dict[str, int] | None = None) -> PlayerContextBuilder:
    return PlayerContextBuilder(FakeNBA(stats=stats, games=games))


def test_empty_player_list_yields_empty_context() -> None:
    assert _builder().build_context_for_players([]) == ""


def test_each_player_gets_one_line_with_name_and_position() -> None:
    out = _builder().build_context_for_players([make_player("A B", position="PG,SG")])
    [line] = out.strip().splitlines()
    assert "A B" in line and "PG,SG" in line


def test_stats_are_appended_when_available() -> None:
    builder = _builder(stats={"A B": PlayerStats(last_5=_stats())})
    out = builder.build_context_for_players([make_player("A B")])
    assert "L5:" in out
    assert "20.0p" in out
    assert "FG52.3%" in out


def test_players_without_stats_still_appear() -> None:
    """A rookie with no game log must not vanish from the waiver list."""
    out = _builder().build_context_for_players([make_player("No Stats")])
    assert "No Stats" in out


def test_remaining_games_are_shown_when_the_window_is_known() -> None:
    builder = _builder(games={"LAL": 4})
    out = builder.build_context_for_players([make_player("A B", team="LAL")], START, END)
    assert "[4G left]" in out


def test_no_schedule_annotation_without_a_matchup_window() -> None:
    builder = _builder(games={"LAL": 4})
    out = builder.build_context_for_players([make_player("A B", team="LAL")])
    assert "G left" not in out


def test_injury_status_and_note_are_surfaced() -> None:
    player = make_player("Hurt Guy", status="O", injury_note="knee")
    out = _builder().build_context_for_players([player])
    assert "[O]" in out
    assert "(knee)" in out


def test_il_slot_is_flagged_separately_from_status() -> None:
    """The prompt's IL rule depends on distinguishing these two."""
    out = _builder().build_context_for_players([make_player("Stashed", status="O", selected_position="IL")])
    assert "[IN IL SPOT]" in out
    assert "[O]" in out


def test_il_plus_counts_as_an_il_slot() -> None:
    out = _builder().build_context_for_players([make_player("Stashed", selected_position="IL+")])
    assert "[IN IL SPOT]" in out


def test_a_normal_bench_slot_is_not_flagged_as_il() -> None:
    out = _builder().build_context_for_players([make_player("Benchie", selected_position="BN")])
    assert "[IN IL SPOT]" not in out


def test_annotations_are_attached_to_the_right_player() -> None:
    a = make_player("Player A", key="a")
    b = make_player("Player B", key="b")
    out = _builder().build_context_for_players([a, b], annotations={"a": "[Top in: BLK]"})
    line_a, line_b = [line for line in out.splitlines() if line]
    assert "[Top in: BLK]" in line_a
    assert "[Top in: BLK]" not in line_b


def test_projections_reach_the_joined_lines_too() -> None:
    """The trade path reads the joined text, and must see what the scout sees."""
    rows = [
        GameProjection(player_id="ab", name="A B", team="LAL", opponent="BOS", date="2026-02-10", stats={"pts": 25})
    ]
    out = _builder().build_context_for_players(
        [make_player("A B")], START, END, projections=ProjectionIndex(rows, START, END)
    )
    assert "PROJ 1G" in out
