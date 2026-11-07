"""What a follow-up conversation is seeded with, instead of the prompt that produced its answer.

The history is resent on every turn, and a generation prompt is dominated by
the candidate pool — the players that were considered and passed over. So a
conversation starts from a briefing: the situation, the constraints and the
roster, plus only what the conversation is about, saying what was left out.
"""

from thefrontoffice.domain.models import CompetitionContext, ScoutReport, TradeProposal

LEFT_OUT = (
    "NOTE: the full candidate pool is not included here. If asked about a player not shown above, say you "
    "would need to re-run the report rather than estimating their numbers."
)


TRADE_LEFT_OUT = (
    "NOTE: the full player lines and the instructions you evaluated the trade from are not included here. "
    "If asked for a figure not shown above or in your evaluation, say you would need to re-run the "
    "evaluation rather than estimating it."
)


def sections(*parts: str) -> str:
    """The parts that say something, as one text: blank ones dropped, each a paragraph."""
    return "\n\n".join(part for part in (p.strip() for p in parts) if part)


def roster(context: CompetitionContext) -> str:
    """The manager's roster, as the prompt carried it."""
    return "".join(context.roster_lines.values()).strip()


def of_report(context: CompetitionContext, report: ScoutReport) -> str:
    """A compact context for follow-up questions about `report`.

    Carries the situation, constraints and full roster — what a "why that
    drop?" needs — plus only the candidates the report actually named. Says
    so, so the model declines rather than inventing numbers for a player it
    cannot see.
    """
    named = {m.player for m in report.moves} | {m.replaces for m in report.moves if m.replaces}
    kept = "".join(line for name, line in context.candidate_lines.items() if name in named).strip()
    return sections(
        "This is a condensed briefing on a report you just produced.",
        context.situation,
        context.constraints,
        context.extra,
        "CURRENT ROSTER:\n" + roster(context),
        "PLAYERS NAMED IN THE REPORT:\n" + (kept or "(none)"),
        LEFT_OUT,
    )


def of_trade(context: CompetitionContext, proposal: TradeProposal) -> str:
    """A compact context for follow-up questions about the trade `context` priced.

    Carries the situation, constraints and roster the evaluation was made
    against and the two sides by name; the evaluation itself is the model's
    turn beside it. Says what was left out, as `of_report` does.
    """
    mine = roster(context)
    return sections(
        "This is a condensed briefing on a trade you just evaluated.",
        context.situation,
        context.constraints,
        context.extra,
        "CURRENT ROSTER:\n" + mine if mine else "",
        f"THE TRADE: giving {', '.join(proposal.giving)}; receiving {', '.join(proposal.receiving)}.",
        TRADE_LEFT_OUT,
    )
