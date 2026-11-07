"""The generic scouting pipeline.

Identical for every competition: ask the provider for a context, get a validated
report back from the model, and open a chat seeded with a briefing rather than
the whole prompt.
"""

import logging

from thefrontoffice.application import briefing
from thefrontoffice.application.answers import Answers, scope
from thefrontoffice.application.formats import ScoutAnswer, VerdictAnswer
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    Move,
    Remembered,
    ScoutReport,
    Stat,
    TaskVerdict,
    task_id,
)
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, ChatSession, ContextProvider

logger = logging.getLogger(__name__)


class ScoutEngine:
    """Turns any ContextProvider into a scouting report."""

    def __init__(self, provider: ContextProvider, *, key: str, ai: AnalysisModel, answers: AnswerStore):
        """Every collaborator is a port, and every one is supplied.

        Deliberately no default: constructing one here would mean naming a
        vendor from the application layer, which is the dependency this layer
        exists to avoid. `bootstrap.Wiring` does the wiring; `key` is the
        competition's registry key, which its judgments are kept under.
        """
        self.provider = provider
        self.key = key
        self.ai = ai
        self.answers = Answers(answers)

    def latest(self, league_id: str) -> Remembered[ScoutReport] | None:
        """The last judgment of this league, without asking anything new."""
        return last_judgment(self.answers, self.key, league_id)

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
        return self.answers.answer(
            scope, context.prompt, ScoutReport, lambda: self._ask(context.prompt, context.headline, context.tasks)
        ).answer

    def _ask(self, prompt: str, headline: list[Stat], tasks: list[Action]) -> ScoutReport:
        answer = self.ai.generate_structured(prompt, ScoutAnswer)

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
            moves=[Move.model_validate(move.model_dump()) for move in answer.moves],
            strategy=answer.strategy,
            tasks=judged,
            headline=headline,
        )

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
