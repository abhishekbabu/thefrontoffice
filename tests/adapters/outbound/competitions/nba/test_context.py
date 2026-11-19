"""Tests for PlayerContextBuilder — the prompt lines both engines share."""

from datetime import date
from typing import Any

from support.nba import FakeNBA, make_player

from thefrontoffice.adapters.outbound.competitions.nba.context import PlayerContextBuilder
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import Line
from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer

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


def _line(player: YahooPlayer, builder: PlayerContextBuilder | None = None, **kwargs: Any) -> str:
    """The one line a player gets."""
    [line] = (builder or _builder()).build_context_for_players([player], **kwargs).strip().splitlines()
    return line


def test_each_player_gets_one_line_with_name_and_position() -> None:
    line = _line(make_player("A B", position="PG,SG"))
    assert "A B" in line and "PG,SG" in line


def test_stats_are_appended_when_available() -> None:
    builder = _builder(stats={"A B": PlayerStats(last_5=_stats())})

    line = _line(make_player("A B"), builder)

    assert "20.0" in line and "52.3" in line
    assert line != _line(make_player("A B"))


def test_a_player_short_of_fifteen_games_also_carries_every_game_he_has() -> None:
    """Twelve games in, his last ten alone would drop two of them."""
    stats = PlayerStats(last_5=_stats(), last_10=_stats(), recent=RecentForm(games=12, line=_stats(PTS=31.0)))

    line = _line(make_player("A B"), _builder(stats={"A B": stats}))

    assert "L12" in line and "31.0" in line


def test_a_full_window_is_not_repeated_as_the_widest_run() -> None:
    stats = PlayerStats(last_15=_stats(), recent=RecentForm(games=15, line=_stats(PTS=31.0)))

    line = _line(make_player("A B"), _builder(stats={"A B": stats}))

    assert "31.0" not in line


def test_players_without_stats_still_appear() -> None:
    """A rookie with no game log must not vanish from the waiver list."""
    assert "No Stats" in _line(make_player("No Stats"))


def test_remaining_games_are_shown_when_the_window_is_known() -> None:
    builder = _builder(games={"LAL": 4})

    known = _line(make_player("A B", team="LAL"), builder, matchup_start=START, matchup_end=END)

    assert known != _line(make_player("A B", team="LAL"), builder)
    assert "[4G left]" in known


def test_no_schedule_annotation_without_a_matchup_window() -> None:
    builder = _builder(games={"LAL": 4})
    assert _line(make_player("A B", team="LAL"), builder) == _line(make_player("A B", team="LAL"))


def test_injury_status_and_note_are_surfaced() -> None:
    line = _line(make_player("Hurt Guy", status="O", injury_note="knee"))
    assert line != _line(make_player("Hurt Guy"))
    assert "knee" in line


def test_the_day_espn_expects_a_hurt_player_back_is_on_his_line() -> None:
    hurt = make_player("Hurt Guy", key="hg", status="O")

    [line] = _builder().build_player_lines([hurt], returns={"hg": date(2026, 11, 22)}).values()

    assert "~22 Nov" in line
    assert "~22 Nov" not in _builder().build_context_for_players([hurt], returns={"other": date(2026, 11, 22)})


def test_il_slot_is_flagged_separately_from_status() -> None:
    """The prompt's IL rule depends on distinguishing these two."""
    stashed = _line(make_player("Stashed", status="O", selected_position="IL"))
    out = _line(make_player("Stashed", status="O"))

    assert stashed != out


def test_il_plus_counts_as_an_il_slot() -> None:
    assert _line(make_player("Stashed", selected_position="IL+")) == _line(
        make_player("Stashed", selected_position="IL")
    )


def test_a_normal_bench_slot_is_not_flagged_as_il() -> None:
    assert _line(make_player("Benchie", selected_position="BN")) == _line(make_player("Benchie"))


def test_annotations_are_attached_to_the_right_player() -> None:
    a = make_player("Player A", key="a")
    b = make_player("Player B", key="b")
    out = _builder().build_context_for_players([a, b], annotations={"a": "[Top in: BLK]"})
    line_a, line_b = [line for line in out.splitlines() if line]
    assert "BLK" in line_a
    assert "BLK" not in line_b


def test_projections_reach_the_joined_lines_too() -> None:
    """The trade path reads the joined text, and must see what the scout sees."""
    rows = [
        GameProjection(player_id="ab", name="A B", team="LAL", opponent="BOS", date="2026-02-10", stats={"pts": 25})
    ]
    out = _builder().build_context_for_players(
        [make_player("A B")], START, END, projections=ProjectionIndex(rows, START, END)
    )
    assert "25.0" in out
