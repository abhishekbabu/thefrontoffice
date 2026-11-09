"""The generic scouting pipeline.

Identical for every competition: ask the provider for a context, get a validated
report back from the model, and open a chat seeded with a briefing rather than
the whole prompt.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from thefrontoffice.application import briefing
from thefrontoffice.application.answers import Answers, is_current, scope
from thefrontoffice.application.formats import ScoutAnswer, VerdictAnswer
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    Judgment,
    Move,
    Remembered,
    ScoutReport,
    TaskVerdict,
    task_id,
)
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, ChatSession, ContextProvider

logger = logging.getLogger(__name__)


class ScoutEngine:
    """Turns any ContextProvider into a scouting report."""

    def __init__(
        self,
        provider: ContextProvider,
        *,
        key: str,
        ai: AnalysisModel,
        answers: AnswerStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        """Every collaborator is a port, and every one is supplied.

        Deliberately no default: constructing one here would mean naming a
        vendor from the application layer, which is the dependency this layer
        exists to avoid. `bootstrap.Wiring` does the wiring; `key` is the
        competition's registry key, which its judgments are kept under.
        """
        self.provider = provider
        self.key = key
        self.ai = ai
        self.clock = clock
        self.answers = Answers(answers, clock)

    def latest(self, league_id: str) -> Judgment | None:
        """The last judgment of this league, without asking anything new, less the moves that have lapsed.

        A judgment is kept until the next is asked for, and the week moves on
        under it: a pickup for a game already played is no move at all, nor
        one a rule added since would have struck. Its moves are read back
        through the week as it stands now; its verdicts are each item's, and
        marked stale where they are (`with_verdicts`). Whether it is due a
        fresh one is read off the same week (`_due`).
        """
        kept = last_judgment(self.answers, self.key, league_id)
        if kept is None:
            return None
        judgment = Judgment.model_validate(kept.model_dump())
        try:
            context = self.provider.build_context(league_id)
        except FrontOfficeError as e:
            logger.warning(f"{self.key}: showing the kept judgment unchecked, the week would not load: {e}")
            return judgment
        moves = self._worth_making(_still_open(kept.answer.moves, context.movable), context.worth)
        return judgment.model_copy(
            update={
                "answer": kept.answer.model_copy(update={"moves": moves}),
                "due": _due(kept, context, self.clock()),
            }
        )

    def report(self, league_id: str) -> ScoutReport:
        """The judged report alone, with no conversation opened beside it.

        What the week's Judge asks for: its questions go to the row they are
        about, not to a chat about the whole report.
        """
        return self._judge(league_id, self.provider.build_context(league_id))

    def start_analysis(self, league_id: str) -> tuple[ScoutReport, ChatSession]:
        """Produce a validated report and open a chat seeded with it.

        Raises:
            FrontOfficeError: the platform failed, or the model returned an
                unusable report.
        """
        context = self.provider.build_context(league_id)
        report = self._judge(league_id, context)

        brief = briefing.of_report(context, report)
        logger.debug(f"{self.key}: briefing is {len(brief):,} chars vs {len(context.prompt):,} for the prompt")
        chat = self.ai.start_chat(
            initial_history=[
                {"role": "user", "parts": [brief]},
                {"role": "model", "parts": [report.model_dump_json()]},
            ]
        )
        return report, chat

    def _judge(self, league_id: str, context: CompetitionContext) -> ScoutReport:
        """The model's report on the week's prompt, or the kept one where nothing it read has changed."""
        scope = scout_scope(self.key, league_id)
        return self.answers.answer(scope, context.prompt, ScoutReport, lambda: self._ask(context)).answer

    def _ask(self, context: CompetitionContext) -> ScoutReport:
        answer = self.ai.generate_structured(context.prompt, ScoutAnswer)
        tasks = context.tasks

        # The figures are the provider's, read off the platform, and the to-do
        # items the provider's too: the model judges them and is never given
        # a field to restate either in, so a hallucinated rank cannot reach
        # the page however the answer reads.
        verdicts = self._verdicts(answer.verdicts, len(tasks))
        judged = [
            task.model_copy(update={"verdict": verdicts.get(task_id(i))}) for i, task in enumerate(tasks, start=1)
        ]
        return ScoutReport(
            situation=answer.situation,
            focus=answer.focus,
            moves=self._worth_making([Move.model_validate(move.model_dump()) for move in answer.moves], context.worth),
            strategy=answer.strategy,
            tasks=judged,
            headline=context.headline,
        )

    def _worth_making(self, moves: list[Move], worth: dict[str, float]) -> list[Move]:
        """The model's moves, less any add worth less a game over the season than the player it drops.

        The same rule the to-do list holds its own pickups to. A model reading
        this week's projections sees a player on bye as nothing and cuts him
        for a one-week body; a prompt can say not to, and this makes sure.
        Where either player's worth is unknown the move stands — there is
        nothing to weigh it by.
        """
        by_name = {_name(name): value for name, value in worth.items()}
        kept = []
        for move in moves:
            added, dropped = by_name.get(_name(move.player)), by_name.get(_name(move.replaces))
            if move.action == "ADD" and added is not None and dropped is not None and dropped > added:
                logger.info(
                    f"{self.key}: dropping a suggested add of {move.player} ({added:.1f} a game) "
                    f"for {move.replaces} ({dropped:.1f} a game)"
                )
                continue
            kept.append(move)
        return kept

    def _verdicts(self, verdicts: list[VerdictAnswer], count: int) -> dict[str, TaskVerdict]:
        """The model's verdicts keyed by task, keeping only ones that name a real task once.

        A verdict on an id the prompt never listed is about nothing, and a
        second verdict on the same task contradicts the first; neither can be
        shown beside a row without one of them being a lie.
        """
        known = {task_id(i) for i in range(1, count + 1)}
        kept: dict[str, TaskVerdict] = {}
        for verdict in verdicts:
            if verdict.task in known and verdict.task not in kept:
                kept[verdict.task] = TaskVerdict.model_validate(verdict.model_dump())
            else:
                logger.warning(f"{self.key}: dropping a verdict on unknown or repeated task {verdict.task!r}")
        if len(kept) < count:
            logger.info(f"{self.key}: the model judged {len(kept)} of {count} to-do items")
        return kept


REJUDGE_AFTER = timedelta(hours=12)
"""How old a judgment of a week that has since changed may grow before it is asked again unprompted.

Long enough that news ticking over through a day costs no call; short enough
that Saturday's judgment is not what Sunday morning reads."""


def _due(kept: Remembered[ScoutReport], context: CompetitionContext, now: datetime) -> bool:
    """Whether the week has moved on far enough to judge it again without being asked.

    An item the judgment never saw is a decision with no verdict, and a new
    week is all such items. Short of that, an item's own wording changing is
    already marked stale beside it, and only age makes it worth a call. A
    week judged on exactly what it is now is never due: the call would
    return the kept answer.
    """
    current = {task.key for task in context.tasks if task.key}
    if not current:
        return False
    judged = {task.key for task in kept.answer.tasks if task.key}
    if current - judged:
        return True
    return not is_current(kept, context.prompt) and now - kept.answered_at > REJUDGE_AFTER


def _still_open(moves: list[Move], movable: frozenset[str] | None) -> list[Move]:
    """The moves every player named in can still be moved: none whose game has kicked off, nor anyone gone since.

    A defense is named by its club ("New Orleans Saints"), as the catalog names it.
    """
    if movable is None:
        return moves
    names = {_name(name) for name in movable}
    return [m for m in moves if _name(m.player) in names and (not m.replaces or _name(m.replaces) in names)]


def _name(written: str) -> str:
    """A player's name as the model wrote it, without the "(WR, ATL)" it tends to add, for matching."""
    return written.split(" (")[0].strip().casefold()


def scout_scope(key: str, league_id: str) -> str:
    """Where a league's judgment of its week is kept."""
    return scope("scout", key, league_id)


def last_judgment(answers: Answers, key: str, league_id: str) -> Remembered[ScoutReport] | None:
    """The league's last judgment of its week, current or not; None where it was never judged."""
    return answers.latest(scout_scope(key, league_id), ScoutReport)


def with_verdicts(actions: list[Action], judged: Remembered[ScoutReport] | None) -> list[Action]:
    """Each item with the verdict last given on the item with its key, marked stale where it reads differently now.

    A verdict on last night's news is not a verdict on this morning's, so it
    stays beside its row but says so rather than passing for a current one.
    """
    if judged is None:
        return actions
    then = {task.key: task for task in judged.answer.tasks if task.key and task.verdict is not None}
    return [
        action.model_copy(update={"verdict": earlier.verdict, "stale": earlier.fingerprint != action.fingerprint})
        if (earlier := then.get(action.key)) is not None
        else action
        for action in actions
    ]
