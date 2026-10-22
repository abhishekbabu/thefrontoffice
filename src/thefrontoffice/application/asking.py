"""Questions asked of one thing on screen.

A follow-up about a whole report has to carry the whole report. A question
about one to-do item or one player needs that item or that player, the roster
around it, and the week's situation — so that is what the conversation is
seeded with, and nothing else. Smaller, so cheaper on every turn it is
resent; and focused, so the answer is about the thing that was asked about.
"""

import logging

from thefrontoffice.domain.errors import SubjectGoneError
from thefrontoffice.domain.models import Action, PlayerDetail, Subject, judgment_scope
from thefrontoffice.domain.ports import AnalysisModel, ChatSession, CompetitionProvider, JudgmentStore

logger = logging.getLogger(__name__)

TASK_ROLE = (
    "You are this fantasy manager's assistant, answering questions about one item on their to-do "
    "list for the week. Answer briefly and concretely from the facts below — role, matchup, news "
    "and the league's own numbers — and say so when a question needs something not shown here."
)
PLAYER_ROLE = (
    "You are this fantasy manager's assistant, answering questions about one player. Answer "
    "briefly and concretely from the facts below, and say so when a question needs something "
    "not shown here."
)


class AnchoredChat:
    """A conversation whose first question carries what it is about.

    The briefing rides with the first message rather than as an invented
    opening exchange, so the history holds only what was actually said.
    """

    def __init__(self, chat: ChatSession, briefing: str) -> None:
        self._chat = chat
        self._briefing: str | None = briefing

    def send_message(self, message: str) -> object:
        if self._briefing is not None:
            message, self._briefing = f"{self._briefing}\n\nQUESTION: {message}", None
        return self._chat.send_message(message)


class AskEngine:
    """Opens a conversation about one subject."""

    def __init__(self, provider: CompetitionProvider, *, ai: AnalysisModel, judgments: JudgmentStore):
        """Every collaborator is a port, supplied by `bootstrap.ask_engine`."""
        self.provider = provider
        self.ai = ai
        self.judgments = judgments

    def open(self, league_id: str, subject: Subject) -> ChatSession:
        """A conversation seeded with `subject`.

        Raises:
            SubjectGoneError: the to-do item is no longer on the list.
            PlayerNotFoundError: no such player.
            AIUnavailableError: no model is configured.
        """
        if subject.kind == "task":
            briefing = self._task_briefing(league_id, subject.key)
        else:
            briefing = self._player_briefing(league_id, subject.key)
        return AnchoredChat(self.ai.start_chat(), briefing)

    def _task_briefing(self, league_id: str, key: str) -> str:
        context = self.provider.build_context(league_id)
        task = next((t for t in context.tasks if t.key == key), None)
        if task is None:
            logger.info(f"{self.provider.label}: asked about {key!r}, which the week no longer holds")
            raise SubjectGoneError()

        judged = self.judgments.latest(judgment_scope(self.provider.label, league_id))
        then = next((t for t in judged.report.tasks if t.key == key), None) if judged else None
        verdict = ""
        if then is not None and then.verdict is not None:
            changed = (
                " The item has changed since, so weigh it against the item as it now reads."
                if then.fingerprint != task.fingerprint
                else ""
            )
            verdict = f"YOUR EARLIER VERDICT: {then.verdict.decision} — {then.verdict.reason}{changed}"

        sections = [
            TASK_ROLE,
            context.situation.strip(),
            context.constraints.strip(),
            "THE ITEM:\n" + _task_text(task),
            verdict,
            "THE ROSTER:\n" + "".join(context.roster_lines.values()).strip(),
        ]
        return "\n\n".join(s for s in sections if s)

    def _player_briefing(self, league_id: str, player_id: str) -> str:
        detail = self.provider.player(league_id, player_id)
        roster = self.provider.roster(league_id)
        roster_text = "\n".join("- " + ", ".join(f"{k}: {v}" for k, v in card.columns.items() if v) for card in roster)
        sections = [PLAYER_ROLE, "THE PLAYER:\n" + _player_text(detail), "THE MANAGER'S ROSTER:\n" + roster_text]
        return "\n\n".join(s for s in sections if s)


def _task_text(task: Action) -> str:
    lines = [f"{task.title} ({task.urgency}, {task.kind})", task.reason]
    if task.when:
        lines.append(f"Deadline: {task.when}")
    lines += [f"- {line.label}: {line.value}" for line in task.evidence]
    return "\n".join(lines)


def _player_text(detail: PlayerDetail) -> str:
    """Everything the drawer shows about him, as lines."""
    lines = [f"{detail.name} — {detail.position}, {detail.team_name or detail.team}"]
    if detail.headline:
        lines.append(f"{detail.headline} {detail.headline_label}".strip())
    if detail.note:
        lines.append(f"Status: {detail.note}")
    for group in detail.groups:
        lines.append(f"{group.title}:")
        lines += [f"- {stat.label}: {stat.value}" for stat in group.stats]
    for table in detail.tables:
        lines.append(f"{table.title} ({', '.join(table.columns)}):")
        lines += [f"- {row.label}: {' | '.join(row.values)}" for row in table.rows]
    return "\n".join(lines)
