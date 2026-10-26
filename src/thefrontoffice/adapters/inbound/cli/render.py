"""Terminal rendering for reports.

The only place that turns the validated models into text. The web UI renders the
same models its own way, and one renderer serves every competition.
"""

import textwrap

from thefrontoffice.domain.models import Move, ScoutReport, Summary, TradeVerdict

_INDENT = "  "


def _wrap(text: str, width: int = 76, indent: str = _INDENT) -> str:
    """Wrap prose to `width`, prefixing every line with `indent`."""
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _render_move(move: Move, number: int) -> str:
    lines = [
        f"{_INDENT}{number}. {move.action} {move.player} ({move.position}, {move.team}) — {move.metric}",
        _wrap(move.rationale, indent=_INDENT + "   "),
    ]
    if move.replaces:
        verb = {"ADD": "DROP", "START": "BENCH", "TRANSFER": "OUT"}.get(move.action, "REPLACES")
        lines.append(f"{_INDENT}   {verb} {move.replaces}")
        if move.replaces_rationale:
            lines.append(_wrap(move.replaces_rationale, indent=_INDENT + "   "))
    return "\n".join(lines)


def render_scout_report(report: ScoutReport) -> str:
    """Render a scout report for the terminal."""
    focus = ", ".join(report.focus) or "none identified"
    parts = [
        f"{_INDENT}SITUATION",
        _wrap(report.situation),
        "",
        f"{_INDENT}Focus: {focus}",
        "",
        f"{_INDENT}MOVES",
    ]
    if report.moves:
        parts.extend(_render_move(m, i) for i, m in enumerate(report.moves, 1))
    else:
        parts.append(f"{_INDENT}   (none returned)")
    parts.extend(["", f"{_INDENT}STRATEGY", _wrap(report.strategy)])
    return "\n".join(parts)


def render_trade_verdict(verdict: TradeVerdict) -> str:
    """Render a trade verdict for the terminal."""
    gained = ", ".join(verdict.gains) or "—"
    lost = ", ".join(verdict.losses) or "—"
    return "\n".join(
        [
            f"{_INDENT}VERDICT: {verdict.verdict}",
            _wrap(verdict.verdict_detail),
            "",
            f"{_INDENT}Gained: {gained}",
            f"{_INDENT}Lost:   {lost}",
            "",
            f"{_INDENT}IMPACT",
            _wrap(verdict.impact),
            "",
            f"{_INDENT}SCHEDULE",
            _wrap(verdict.schedule),
            "",
            f"{_INDENT}RISK",
            _wrap(verdict.risk),
            "",
            f"{_INDENT}STRATEGY",
            _wrap(verdict.strategy),
        ]
    )


def render_week(summary: Summary) -> str:
    """Render the week for the terminal: its figures, then what to do, most urgent first.

    Items the manager dismissed or snoozed stay out, as they do on the page.
    """
    parts = [f"{_INDENT}{stat.label}: {stat.value}" for stat in summary.headline]
    if summary.actions is None:
        return "\n".join(parts)
    shown = [action for action in summary.actions if not action.hidden]
    parts.extend(["", f"{_INDENT}TO DO"])
    if not shown:
        parts.append(f"{_INDENT}   Nothing to do.")
    for action in shown:
        change = f" ({action.win_change * 100:+.1f}% to win)" if action.win_change is not None else ""
        parts.append(f"{_INDENT}   [{action.urgency}] {action.title}{change}")
        parts.append(_wrap(action.reason, indent=_INDENT + "     "))
    return "\n".join(parts)
