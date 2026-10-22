"""Tests for the scouting pipeline: `application/scouting.py`.

The provider is a stand-in returning a fixed context, since what is under test
is what the engine does with the model's answer — not how a context is built.
"""

from typing import Any

from conftest import FakeAI
from reports import MOCK_NBA_REPORT

from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.domain.models import Action, CompetitionContext, ScoutReport, Stat, TaskVerdict, task_id

TASKS = [
    Action(kind="lineup", urgency="now", title="Start A over B", reason="B is out.", player_id="a"),
    Action(kind="lineup", urgency="soon", title="Start C over D", reason="+2.5 proj pts.", player_id="c"),
]


class ContextOnly:
    """A provider that has already gathered its week."""

    competition = "nfl"

    def __init__(self, tasks: list[Action]) -> None:
        self.context = CompetitionContext(prompt="prompt", headline=[Stat(label="Week", value="7")], tasks=tasks)

    def build_context(self, league_id: str) -> CompetitionContext:
        return self.context


def _report(*verdicts: TaskVerdict, tasks: list[Action] | None = None) -> ScoutReport:
    return MOCK_NBA_REPORT.model_copy(update={"verdicts": list(verdicts), "tasks": tasks or []})


def _verdict(position: int, decision: Any = "AGREE") -> TaskVerdict:
    return TaskVerdict(task=task_id(position), decision=decision, reason="because")


def _run(report: ScoutReport, tasks: list[Action] = TASKS) -> ScoutReport:
    engine = ScoutEngine(ContextOnly(tasks), ai=FakeAI(report=report))  # type: ignore[arg-type]
    judged, _ = engine.start_analysis("L1")
    return judged


def test_each_verdict_is_put_beside_the_task_it_names() -> None:
    report = _run(_report(_verdict(2, "OVERRULE"), _verdict(1, "AGREE")))

    assert [t.player_id for t in report.tasks] == ["a", "c"]
    assert [t.verdict.decision if t.verdict else None for t in report.tasks] == ["AGREE", "OVERRULE"]


def test_a_task_the_model_skipped_is_kept_without_a_verdict() -> None:
    """The list is the page's, not the model's: skipping an item cannot remove it."""
    report = _run(_report(_verdict(1)))

    assert len(report.tasks) == 2
    assert report.tasks[1].verdict is None


def test_a_verdict_on_a_task_that_was_never_listed_is_dropped() -> None:
    report = _run(_report(_verdict(1), _verdict(3)))

    assert [v.task for v in report.verdicts] == [task_id(1)]


def test_only_the_first_of_two_verdicts_on_one_task_counts() -> None:
    """Two would contradict each other beside the same row."""
    report = _run(_report(_verdict(1, "AGREE"), _verdict(1, "OVERRULE")))

    assert report.tasks[0].verdict is not None and report.tasks[0].verdict.decision == "AGREE"
    assert len(report.verdicts) == 1


def test_tasks_the_model_writes_itself_are_discarded() -> None:
    """It judges the list; it does not get to restate it."""
    invented = Action(kind="waiver", urgency="now", title="Pick up Nobody", reason="trust me", player_id="x")

    report = _run(_report(tasks=[invented]))

    assert "x" not in [t.player_id for t in report.tasks]


def test_a_competition_with_no_tasks_reports_none() -> None:
    report = _run(_report(_verdict(1)), tasks=[])

    assert (report.tasks, report.verdicts) == ([], [])


def test_the_headline_still_comes_from_the_provider() -> None:
    assert [s.label for s in _run(_report()).headline] == ["Week"]
