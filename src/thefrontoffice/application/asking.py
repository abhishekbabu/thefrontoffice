"""Questions asked of what is on screen.

A follow-up about a whole report has to carry the whole report. A question
about one to-do item, one player or one page needs that thing, the roster
around it, and the week's situation — so that is what the conversation is
briefed with, and nothing else. Smaller, so cheaper on every turn it is
resent; and focused, so the answer is about the thing that was asked about.

The assistant follows the manager around a league: it is briefed on each
page and player the first time a question is asked with it on screen, rather
than on everything at once, so its history holds only what was looked at.
"""

import logging
from collections.abc import Callable, Sequence

from thefrontoffice.application import briefing
from thefrontoffice.application.answers import Answers
from thefrontoffice.application.scouting import last_judgment, standing_moves, with_verdicts
from thefrontoffice.domain.errors import SubjectGoneError
from thefrontoffice.domain.models import (
    Action,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerQuery,
    Subject,
)
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, ChatReply, ChatSession, SubjectProvider

logger = logging.getLogger(__name__)

ROLE = (
    "You are this fantasy manager's assistant, open beside their league in The Front Office. "
    "Each message says what is on their screen. The facts of each page, player and to-do item arrive "
    "the first time it is on screen, as of that moment. Answer briefly and concretely from those "
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

Briefing = tuple[str, str]
"""What to call a subject where the conversation names it, and the facts about it."""


class Assistant:
    """A conversation that follows the manager from page to page.

    Each question names what is on screen. Whatever has not been briefed yet
    is briefed with that question, once; what has been is already in the
    history, which is resent every turn, so briefing it again would only make
    every later turn dearer.
    """

    def __init__(self, chat: ChatSession, brief: Callable[[Subject], Briefing]) -> None:
        self._chat = chat
        self._brief = brief
        self._briefed: dict[tuple[str, str], str] = {}
        self._answered = False

    def ask(self, message: str, on_screen: Sequence[Subject]) -> ChatReply:
        """Ask `message` with `on_screen` in view, briefing whatever is new.

        Nothing counts as briefed until the model has answered: a question
        that failed was never taken into the conversation, and neither was
        what rode with it.

        Raises:
            SubjectGoneError: a to-do item on screen is no longer on the list.
            PlayerNotFoundError: a player on screen does not exist.
        """
        sections = [] if self._answered else [ROLE]
        new: dict[tuple[str, str], str] = {}
        names: list[str] = []
        for subject in on_screen:
            seen = (subject.kind, subject.key)
            name = self._briefed.get(seen) or new.get(seen)
            if name is None:
                name, facts = self._brief(subject)
                sections.append(facts)
                new[seen] = name
            names.append(name)
        sections += ["ON SCREEN NOW: " + ("; ".join(names) or "no page of this league"), f"QUESTION: {message}"]
        reply = self._chat.send_message(briefing.sections(*sections))
        self._briefed |= new
        self._answered = True
        return reply


class AskEngine:
    """Opens the conversation that is briefed on what is on screen."""

    def __init__(self, provider: SubjectProvider, *, key: str, ai: AnalysisModel, answers: AnswerStore):
        """Every collaborator is a port, supplied by `bootstrap.Wiring`; `key` names the competition."""
        self.provider = provider
        self.key = key
        self.ai = ai
        self.answers = Answers(answers)

    def assistant(self, league_id: str) -> Assistant:
        """A conversation that is briefed on each page, player and item as they come on screen.

        Raises:
            AIUnavailableError: no model is configured.
        """
        return Assistant(self.ai.start_chat(), lambda subject: self.brief(league_id, subject))

    def brief(self, league_id: str, subject: Subject) -> Briefing:
        """What to call `subject`, and the facts about it.

        Raises:
            SubjectGoneError: the to-do item is no longer on the list.
            PlayerNotFoundError: no such player.
        """
        if subject.kind == "task":
            return self._task_briefing(league_id, subject.key)
        if subject.kind == "player":
            return self._player_briefing(league_id, subject.key)
        return self._page_briefing(league_id, subject.key)

    def _task_briefing(self, league_id: str, key: str) -> Briefing:
        context = self.provider.build_context(league_id)
        task = next((t for t in context.tasks if t.key == key), None)
        if task is None:
            logger.info(f"{self.key}: asked about {key!r}, which the week no longer holds")
            raise SubjectGoneError()

        [task] = with_verdicts([task], last_judgment(self.answers, self.key, league_id))
        verdict = ""
        if task.verdict is not None:
            changed = " The item has changed since, so weigh it against the item as it now reads." if task.stale else ""
            verdict = f"YOUR EARLIER VERDICT: {task.verdict.decision} — {task.verdict.reason}{changed}"

        facts = briefing.sections(
            context.situation,
            context.constraints,
            "THE ITEM:\n" + _task_text(task),
            verdict,
            briefing.titled("THE ROSTER", briefing.roster(context)),
        )
        return f"the to-do item {task.title!r}", facts

    def _player_briefing(self, league_id: str, player_id: str) -> Briefing:
        detail = self.provider.player(league_id, player_id)
        roster = self.provider.roster(league_id)
        facts = briefing.sections(
            "THE PLAYER:\n" + _player_text(detail),
            briefing.titled("THE MANAGER'S ROSTER", _cards_text(roster)),
        )
        return detail.name, facts

    def _page_briefing(self, league_id: str, page: str) -> Briefing:
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
            facts = briefing.sections(
                briefing.titled("THE MANAGER'S ROSTER", _cards_text(self.provider.roster(league_id))),
                briefing.titled("WHAT EACH RESTS ON", briefing.roster(self.provider.build_context(league_id))),
            )
        else:
            pool = self.provider.free_agents(league_id, PlayerQuery(limit=FREE_AGENTS_SHOWN))
            facts = f"THE BEST {len(pool.players)} FREE AGENTS OF {pool.total}:\n" + _cards_text(pool.players)
        return name, f"THE PAGE — {name.upper()}:\n{facts}"

    def _week_text(self, league_id: str) -> str:
        """The week as its page shows it: the situation, and one to-do list with the last judgment's word in it."""
        context = self.provider.build_context(league_id)
        judged = last_judgment(self.answers, self.key, league_id)
        items = [
            _task_text(task)
            + (f"\nYour verdict: {task.verdict.decision} — {task.verdict.reason}" if task.verdict else "")
            for task in with_verdicts(context.tasks, judged)
        ]
        # A move the last judgment added is a row on the page like any other,
        # so a list read without them says there is nothing to do beside one.
        # Only the ones that still stand, as the page shows them.
        if judged is not None:
            items += [
                f"Suggested by your last judgment: {m.action} {m.player} ({m.position}, {m.team})"
                + (f" in place of {m.replaces}" if m.replaces else "")
                + f" — {m.metric}. {m.rationale}"
                for m in standing_moves(judged.answer.moves, context, self.key)
            ]
        return briefing.sections(
            context.situation,
            context.constraints,
            "THE TO-DO LIST, AS THE PAGE SHOWS IT:\n" + ("\n\n".join(items) or "Nothing to do."),
            f"YOUR PLAN FOR THE WEEK: {judged.answer.strategy}" if judged else "",
            briefing.titled("THE ROSTER", briefing.roster(context)),
        )


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
    standings = [
        f"{row.rank}. {row.name}{' (you)' if row.is_mine else ''} — "
        + ", ".join(part for part in (row.record, row.points, row.playoffs and f"playoffs {row.playoffs}") if part)
        for row in schedule.standings
    ]
    season = [
        f"{row.label}{' (now)' if row.is_current else ''}: "
        + (f"vs {row.opponent}" if row.opponent else "bye")
        + (f" — {row.result}" if row.result else "")
        for row in schedule.season
    ]
    activity = [f"{row.when} {row.who}: {row.what} {row.detail}".strip() for row in schedule.activity[:ACTIVITY_SHOWN]]
    return (
        briefing.sections(
            "\n".join(f"{stat.label}: {stat.value}" for stat in schedule.headline),
            briefing.titled("STANDINGS", "\n".join(standings)),
            briefing.titled("YOUR SEASON", "\n".join(season)),
            briefing.titled("RECENT MOVES", "\n".join(activity)),
        )
        or "Nothing published for this league yet."
    )
