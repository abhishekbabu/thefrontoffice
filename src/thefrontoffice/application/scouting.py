"""The generic scouting pipeline.

Identical for every competition: ask the provider for a context, get a validated
report back from the model, and open a chat seeded with a briefing rather than
the whole prompt.
"""

import hashlib
import logging
from datetime import datetime, timezone

from thefrontoffice.domain.models import Action, Judgment, ScoutReport, Stat, TaskVerdict, task_id
from thefrontoffice.domain.ports import AnalysisModel, ChatSession, CompetitionProvider, JudgmentStore

logger = logging.getLogger(__name__)


class ScoutEngine:
    """Turns any CompetitionProvider into a scouting report."""

    def __init__(self, provider: CompetitionProvider, *, ai: AnalysisModel, judgments: JudgmentStore):
        """Every collaborator is a port, and every one is supplied.

        Deliberately no default: constructing one here would mean naming a
        vendor from the application layer, which is the dependency this layer
        exists to avoid. `bootstrap.scout_engine` does the wiring.
        """
        self.provider = provider
        self.ai = ai
        self.judgments = judgments

    @property
    def _scope(self) -> str:
        """Whose judgment this is: the competition on its platform, then the league."""
        return self.provider.label

    def latest(self, league_id: str) -> Judgment | None:
        """The last judgment of this league, without asking anything new."""
        return self.judgments.latest(f"{self._scope}:{league_id}")

    def start_analysis(self, league_id: str) -> tuple[ScoutReport, ChatSession]:
        """Produce a validated report and open a chat seeded with it.

        Raises:
            FrontOfficeError: the platform failed, or the model returned an
                unusable report.
        """
        context = self.provider.build_context(league_id)
        report = self._judge(league_id, context.prompt, context.headline, context.tasks)

        briefing = context.briefing(report)
        logger.debug(
            f"{self.provider.competition}: briefing is {len(briefing):,} chars vs {len(context.prompt):,} for the prompt"
        )
        chat = self.ai.start_chat(
            initial_history=[
                {"role": "user", "parts": [briefing]},
                {"role": "model", "parts": [report.model_dump_json()]},
            ]
        )
        return report, chat

    def _judge(self, league_id: str, prompt: str, headline: list[Stat], tasks: list[Action]) -> ScoutReport:
        """The model's report on `prompt`, or the stored one where nothing it read has changed.

        Asking again about an unchanged week spends a call for the same answer,
        and on a free tier a call is the scarce thing.
        """
        scope = f"{self._scope}:{league_id}"
        inputs = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        stored = self.judgments.latest(scope)
        if stored is not None and stored.inputs == inputs:
            logger.info(f"{scope}: nothing has changed since the last judgment; reusing it")
            return stored.report

        report = self.ai.generate_structured(prompt, ScoutReport)

        # The provider read these off the platform; the model was told to leave
        # the field empty but is not trusted to. Overwriting rather than merging
        # means a hallucinated rank can never reach the page. The to-do items
        # likewise: the model judges them, it does not get to restate them.
        verdicts = self._verdicts(report.verdicts, len(tasks))
        judged = [task.model_copy(update={"verdict": verdicts.get(task_id(i))}) for i, task in _numbered(tasks)]
        report = report.model_copy(update={"headline": headline, "tasks": judged, "verdicts": list(verdicts.values())})
        self.judgments.save(scope, Judgment(report=report, judged_at=datetime.now(timezone.utc), inputs=inputs))
        return report

    def _verdicts(self, verdicts: list[TaskVerdict], count: int) -> dict[str, TaskVerdict]:
        """The model's verdicts keyed by task, keeping only ones that name a real task once.

        A verdict on an id the prompt never listed is about nothing, and a
        second verdict on the same task contradicts the first; neither can be
        shown beside a row without one of them being a lie.
        """
        known = {task_id(i) for i in range(1, count + 1)}
        kept: dict[str, TaskVerdict] = {}
        for verdict in verdicts:
            if verdict.task in known and verdict.task not in kept:
                kept[verdict.task] = verdict
            else:
                logger.warning(
                    f"{self.provider.competition}: dropping a verdict on unknown or repeated task {verdict.task!r}"
                )
        if len(kept) < count:
            logger.info(f"{self.provider.competition}: the model judged {len(kept)} of {count} to-do items")
        return kept


def _numbered(tasks: list[Action]) -> list[tuple[int, Action]]:
    return list(enumerate(tasks, start=1))
