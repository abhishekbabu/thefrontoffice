"""Tests for terminal rendering of structured reports."""

from support.reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.inbound.cli.render import render_scout_report, render_trade_verdict, render_week
from thefrontoffice.domain.models import Move, ScoutReport, Side, Summary, Swap


def _rec(**overrides: object) -> Move:
    base: dict[str, object] = {
        "action": "ADD",
        "player": "Test Player",
        "position": "PF",
        "team": "LAL",
        "metric": "3 games left",
        "rationale": "Rebounds at volume.",
        "replaces": "Bench Guy",
        "replaces_rationale": "No categories won.",
    }
    base.update(overrides)
    return Move.model_validate(base)


def test_scout_report_surfaces_every_field() -> None:
    out = render_scout_report(MOCK_NBA_REPORT)
    assert all(focus in out for focus in MOCK_NBA_REPORT.focus)
    for rec in MOCK_NBA_REPORT.moves:
        assert rec.player in out
        assert rec.replaces in out


def test_recommendations_are_numbered_in_order() -> None:
    out = render_scout_report(MOCK_NBA_REPORT)
    titles = [move.title for move in MOCK_NBA_REPORT.moves]
    assert out.index(f"1. {titles[0]}") < out.index(f"2. {titles[1]}") < out.index(f"3. {titles[2]}")


def test_a_move_with_no_drop_target_carries_no_drop_reasoning() -> None:
    """With 0 adds left the model returns MONITOR entries and no drop target; a stray reason would name nobody."""
    watch = _rec(action="MONITOR", replaces="", replaces_rationale="Left over.")
    out = render_scout_report(ScoutReport(situation="No adds left.", focus=["BLK"], moves=[watch], strategy="Hold."))
    assert watch.title in out
    assert "Left over." not in out


def test_empty_target_list_is_stated_explicitly() -> None:
    """Rather than a heading with nothing under it, which reads as a rendering fault."""
    out = render_scout_report(ScoutReport(situation="x", focus=[], moves=[], strategy="y"))
    assert out.split("MOVES")[1].split("STRATEGY")[0].strip()


def test_long_prose_is_wrapped_not_truncated() -> None:
    long_text = "word " * 200
    report = ScoutReport(situation=long_text, focus=[], moves=[], strategy="y")
    out = render_scout_report(report)
    assert max(len(line) for line in out.splitlines()) <= 80
    assert out.count("word") == 200  # nothing dropped


def test_trade_verdict_surfaces_every_field() -> None:
    out = render_trade_verdict(MOCK_NBA_VERDICT)
    assert MOCK_NBA_VERDICT.verdict in out
    for cat in MOCK_NBA_VERDICT.gains:
        assert cat in out


def test_empty_category_lists_render_as_a_dash() -> None:
    from thefrontoffice.domain.models import TradeVerdict

    v = TradeVerdict(
        verdict="REJECT",
        verdict_detail="d",
        gains=[],
        losses=[],
        impact="i",
        schedule="s",
        risk="r",
        strategy="st",
    )
    out = render_trade_verdict(v)
    lists = [line.split(":", 1)[1].strip() for line in out.splitlines() if line.strip().startswith(("Gained", "Lost"))]
    assert lists == ["—", "—"]


def test_the_week_shows_the_changes_the_projections_imply_as_the_page_does() -> None:
    """A competition with no to-do list sends its swaps to be shown; the terminal dropped them."""
    out = render_week(
        Summary(swaps=[Swap(start="Saka", out="Foden", gain="+2.1 xPts"), Swap(start="Isak", gain="+4.0")])
    )

    assert all(name in out for name in ("Saka", "Foden", "+2.1 xPts", "Isak"))


def test_a_head_to_head_week_names_both_teams_and_their_points() -> None:
    """The page says these in the card headers; the terminal has no cards, so it says them first."""
    out = render_week(
        Summary(
            mine=Side(name="Your lineup", detail="7-3", points="61.20 pts"),
            opponent=Side(name="Rival", detail="3-7", points="58.00 pts"),
        )
    )

    assert all(fact in out for fact in ("Rival", "3-7", "58.00 pts", "61.20 pts"))


def test_a_week_with_nobody_to_play_names_no_teams() -> None:
    assert "Your lineup" not in render_week(Summary(mine=Side(name="Your lineup", points="61.20 pts")))
