"""Tests for terminal rendering of structured reports."""

from reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.inbound.cli.render import render_scout_report, render_trade_verdict
from thefrontoffice.domain.models import Move, ScoutReport


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
    assert "SITUATION" in out
    assert "MOVES" in out
    assert "STRATEGY" in out
    for rec in MOCK_NBA_REPORT.moves:
        assert rec.player in out
        assert rec.replaces in out


def test_recommendations_are_numbered_in_order() -> None:
    out = render_scout_report(MOCK_NBA_REPORT)
    assert out.index("1. ADD") < out.index("2. ADD") < out.index("3. ADD")


def test_monitor_entries_render_without_a_drop() -> None:
    """With 0 adds left the model returns MONITOR entries and no drop target."""
    report = ScoutReport(
        situation="No adds left.",
        focus=["BLK"],
        moves=[_rec(action="MONITOR", replaces="", replaces_rationale="")],
        strategy="Hold.",
    )
    out = render_scout_report(report)
    assert "MONITOR Test Player" in out
    assert "DROP" not in out


def test_empty_target_list_is_stated_explicitly() -> None:
    report = ScoutReport(situation="x", focus=[], moves=[], strategy="y")
    assert "(none returned)" in render_scout_report(report)


def test_long_prose_is_wrapped_not_truncated() -> None:
    long_text = "word " * 200
    report = ScoutReport(situation=long_text, focus=[], moves=[], strategy="y")
    out = render_scout_report(report)
    assert max(len(line) for line in out.splitlines()) <= 80
    assert out.count("word") == 200  # nothing dropped


def test_trade_verdict_surfaces_every_field() -> None:
    out = render_trade_verdict(MOCK_NBA_VERDICT)
    for heading in ("VERDICT:", "IMPACT", "SCHEDULE", "RISK", "STRATEGY"):
        assert heading in out
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
    assert "Gained: —" in out
    assert "Lost:   —" in out
