"""Questions asked of what is on screen.

A follow-up about a whole report has to carry the whole report. A question
about one to-do item or one player needs that item or that player, the roster
around it, and the week's situation — so that is what the conversation is
seeded with, and nothing else. Smaller, so cheaper on every turn it is
resent; and focused, so the answer is about the thing that was asked about.

The assistant is the same idea followed around the app: it is briefed on each
page and player the first time a question is asked with it on screen, rather
than on everything at once, so its history holds only what was looked at.
"""

import logging
from collections.abc import Callable, Sequence

from thefrontoffice.application.answers import Answers
from thefrontoffice.application.scouting import scout_scope
from thefrontoffice.domain.errors import SubjectGoneError
from thefrontoffice.domain.models import (
    Action,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerQuery,
    ScoutReport,
    Subject,
)
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, ChatReply, ChatSession, SubjectProvider

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
PAGE_ROLE = (
    "You are this fantasy manager's assistant, answering questions about one page of their "
    "league. Answer briefly and concretely from the facts below, and say so when a question "
    "needs something not shown here."
)
ASSISTANT_ROLE = (
    "You are this fantasy manager's assistant, open beside their league in The Front Office. "
    "Each message says what is on their screen. The facts of each page and player arrive the "
    "first time they are on screen, as of that moment. Answer briefly and concretely from those "
    "facts — role, usage, trend, news and matchup ahead of any projection — and say so when a "
    "question needs something not shown."
)

FREE_AGENTS_SHOWN = 25
"""Free agents a briefing lists: the top of the pool as the page opens on it."""

ACTIVITY_SHOWN = 15
"""League moves a briefing lists, most recent first."""

PAGE_NAMES = {
    "week": "the week — lineup, matchup and to-do list",
    "league": "the league — standings, season and activity",
    "team": "their roster",
    "free-agents": "the free agents",
}


class AnchoredChat:
    """A conversation whose first question carries what it is about.

    The briefing rides with the first message rather than as an invented
    opening exchange, so the history holds only what was actually said.
    """

    def __init__(self, chat: ChatSession, briefing: str) -> None:
        self._chat = chat
        self._briefing: str | None = briefing

    def send_message(self, message: str) -> ChatReply:
        if self._briefing is not None:
            message, self._briefing = f"{self._briefing}\n\nQUESTION: {message}", None
        return self._chat.send_message(message)


class Assistant:
    """A conversation that follows the manager from page to page.

    Each question names what is on screen. Whatever has not been briefed yet
    is briefed with that question, once; what has been is already in the
    history, which is resent every turn, so briefing it again would only make
    every later turn dearer.
    """

    def __init__(self, chat: ChatSession, brief: Callable[[Subject], tuple[str, str]]) -> None:
        """`brief` answers a subject with what to call it and the facts about it."""
        self._chat = chat
        self._brief = brief
        self._names: dict[tuple[str, str], str] = {}
        self._started = False

    def ask(self, message: str, on_screen: Sequence[Subject]) -> ChatReply:
        """Ask `message` with `on_screen` in view, briefing whatever is new.

        Raises:
            SubjectGoneError: a to-do item on screen is no longer on the list.
            PlayerNotFoundError: a player on screen does not exist.
        """
        sections = [] if self._started else [ASSISTANT_ROLE]
        names: list[str] = []
        for subject in on_screen:
            seen = (subject.kind, subject.key)
            if seen not in self._names:
                name, facts = self._brief(subject)
                sections.append(facts)
                self._names[seen] = name
            names.append(self._names[seen])
        sections.append("ON SCREEN NOW: " + ("; ".join(names) or "no page of this league"))
        sections.append(f"QUESTION: {message}")
        reply = self._chat.send_message("\n\n".join(s for s in sections if s))
        self._started = True
        return reply


class AskEngine:
    """Opens a conversation about what is on screen."""

    def __init__(self, provider: SubjectProvider, *, ai: AnalysisModel, answers: AnswerStore):
        """Every collaborator is a port, supplied by `bootstrap.ask_engine`."""
        self.provider = provider
        self.ai = ai
        self.answers = Answers(answers)

    def open(self, league_id: str, subject: Subject) -> ChatSession:
        """A conversation seeded with `subject`.

        Raises:
            SubjectGoneError: the to-do item is no longer on the list.
            PlayerNotFoundError: no such player.
            AIUnavailableError: no model is configured.
        """
        role = {"task": TASK_ROLE, "player": PLAYER_ROLE, "page": PAGE_ROLE}[subject.kind]
        _, facts = self.brief(league_id, subject)
        return AnchoredChat(self.ai.start_chat(), f"{role}\n\n{facts}")

    def assistant(self, league_id: str) -> Assistant:
        """A conversation that is briefed on each page and player as they come on screen.

        Raises:
            AIUnavailableError: no model is configured.
        """
        return Assistant(self.ai.start_chat(), lambda subject: self.brief(league_id, subject))

    def brief(self, league_id: str, subject: Subject) -> tuple[str, str]:
        """What to call `subject`, and the facts about it a conversation is seeded with.

        Raises:
            SubjectGoneError: the to-do item is no longer on the list.
            PlayerNotFoundError: no such player.
        """
        if subject.kind == "task":
            return self._task_briefing(league_id, subject.key)
        if subject.kind == "player":
            return self._player_briefing(league_id, subject.key)
        return self._page_briefing(league_id, subject.key)

    def _task_briefing(self, league_id: str, key: str) -> tuple[str, str]:
        context = self.provider.build_context(league_id)
        task = next((t for t in context.tasks if t.key == key), None)
        if task is None:
            logger.info(f"{self.provider.label}: asked about {key!r}, which the week no longer holds")
            raise SubjectGoneError()

        sections = [
            context.situation.strip(),
            context.constraints.strip(),
            "THE ITEM:\n" + _task_text(task),
            self._verdict(league_id, task),
            "THE ROSTER:\n" + "".join(context.roster_lines.values()).strip(),
        ]
        return f"the to-do item {task.title!r}", "\n\n".join(s for s in sections if s)

    def _verdict(self, league_id: str, task: Action) -> str:
        """The last judgment's verdict on this item, flagged where the item has moved since."""
        judged = self.answers.latest(scout_scope(self.provider.label, league_id), ScoutReport)
        then = next((t for t in judged.answer.tasks if t.key == task.key), None) if judged else None
        if then is None or then.verdict is None:
            return ""
        changed = (
            " The item has changed since, so weigh it against the item as it now reads."
            if then.fingerprint != task.fingerprint
            else ""
        )
        return f"YOUR EARLIER VERDICT: {then.verdict.decision} — {then.verdict.reason}{changed}"

    def _player_briefing(self, league_id: str, player_id: str) -> tuple[str, str]:
        detail = self.provider.player(league_id, player_id)
        roster = self.provider.roster(league_id)
        sections = ["THE PLAYER:\n" + _player_text(detail), "THE MANAGER'S ROSTER:\n" + _cards_text(roster)]
        return detail.name, "\n\n".join(sections)

    def _page_briefing(self, league_id: str, page: str) -> tuple[str, str]:
        name = PAGE_NAMES.get(page)
        if name is None:
            # A page with no league facts behind it. Saying which it is still
            # tells the model where the manager is looking.
            return f"the {page} page", ""
        if page == "week":
            facts = self._week_text(league_id)
        elif page == "league":
            facts = _schedule_text(self.provider.schedule(league_id))
        elif page == "team":
            # The table, and what each row rests on — role, matchup, news —
            # which the table's columns cannot carry.
            context = self.provider.build_context(league_id)
            facts = "\n\n".join(
                [
                    "THE MANAGER'S ROSTER:\n" + _cards_text(self.provider.roster(league_id)),
                    "WHAT EACH RESTS ON:\n" + "".join(context.roster_lines.values()).strip(),
                ]
            )
        else:
            pool = self.provider.free_agents(league_id, PlayerQuery(limit=FREE_AGENTS_SHOWN))
            facts = f"THE BEST {len(pool.players)} FREE AGENTS OF {pool.total}:\n" + _cards_text(pool.players)
        return name, f"THE PAGE — {name.upper()}:\n{facts}"

    def _week_text(self, league_id: str) -> str:
        context = self.provider.build_context(league_id)
        plan, verdicts, moves = self._judgment(league_id)
        # One list, as the page shows it: a move the last judgment added is a
        # row on it like any other, so a list read without them says there is
        # nothing to do beside one.
        items = [_task_text(task) + verdicts.get(task.key, "") for task in context.tasks] + moves
        sections = [
            context.situation.strip(),
            context.constraints.strip(),
            "THE TO-DO LIST, AS THE PAGE SHOWS IT:\n" + ("\n\n".join(items) or "Nothing to do."),
            plan,
            "THE ROSTER:\n" + "".join(context.roster_lines.values()).strip(),
        ]
        return "\n\n".join(s for s in sections if s)

    def _judgment(self, league_id: str) -> tuple[str, dict[str, str], list[str]]:
        """The week's last judgment: its plan, a verdict line per item it judged, and the moves it added."""
        judged = self.answers.latest(scout_scope(self.provider.label, league_id), ScoutReport)
        if judged is None:
            return "", {}, []
        report = judged.answer
        verdicts = {
            t.key: f"\nYour verdict: {t.verdict.decision} — {t.verdict.reason}" for t in report.tasks if t.verdict
        }
        moves = [
            f"Suggested by your last judgment: {m.action} {m.player} ({m.position}, {m.team})"
            + (f" in place of {m.replaces}" if m.replaces else "")
            + f" — {m.metric}. {m.rationale}"
            for m in report.moves
        ]
        return f"YOUR PLAN FOR THE WEEK: {report.strategy}", verdicts, moves


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


def _cards_text(cards: Sequence[PlayerCard]) -> str:
    """One line a player, in the table's own columns."""
    return "\n".join("- " + ", ".join(f"{k}: {v}" for k, v in card.columns.items() if v) for card in cards)


def _schedule_text(schedule: LeagueSchedule) -> str:
    """The league page, section by section, leaving out whatever the platform does not have."""
    sections = []
    if schedule.headline:
        sections.append("\n".join(f"{stat.label}: {stat.value}" for stat in schedule.headline))
    if schedule.standings:
        rows = [
            f"{row.rank}. {row.name}{' (you)' if row.is_mine else ''} — "
            + ", ".join(part for part in (row.record, row.points, row.playoffs and f"playoffs {row.playoffs}") if part)
            for row in schedule.standings
        ]
        sections.append("STANDINGS:\n" + "\n".join(rows))
    if schedule.season:
        rows = [
            f"{row.label}{' (now)' if row.is_current else ''}: "
            + (f"vs {row.opponent}" if row.opponent else "bye")
            + (f" — {row.result}" if row.result else "")
            for row in schedule.season
        ]
        sections.append("YOUR SEASON:\n" + "\n".join(rows))
    if schedule.activity:
        rows = [f"{row.when} {row.who}: {row.what} {row.detail}".strip() for row in schedule.activity[:ACTIVITY_SHOWN]]
        sections.append("RECENT MOVES:\n" + "\n".join(rows))
    return "\n\n".join(sections) or "Nothing published for this league yet."
