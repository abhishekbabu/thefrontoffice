"""Tests for the scouting pipeline: `application/scouting.py`.

The provider is a stand-in returning a fixed context, since what is under test
is what the engine does with the model's answer — not how a context is built.
"""

from dataclasses import replace
from typing import Any

from support.ai import FakeAI
from support.reports import MOCK_NBA_REPORT
from support.stores import FakeAnswers

from thefrontoffice.application.formats import ScoutAnswer, VerdictAnswer
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.domain.errors import PlatformError
from thefrontoffice.domain.models import Action, CompetitionContext, ScoutReport, Stat, task_id

TASKS = [
    Action(kind="lineup", urgency="now", title="Start A over B", reason="B is out.", player_id="a"),
    Action(kind="lineup", urgency="soon", title="Start C over D", reason="+2.5 proj pts.", player_id="c"),
]


class ContextOnly:
    """A provider that has already gathered its week, whose prompt a test can change."""

    def __init__(self, tasks: list[Action], prompt: str = "prompt") -> None:
        self.context = CompetitionContext(prompt=prompt, headline=[Stat(label="Week", value="7")], tasks=tasks)

    def build_context(self, league_id: str) -> CompetitionContext:
        return self.context


def _report(*verdicts: VerdictAnswer) -> ScoutAnswer:
    """What the model writes: the mock report's judgement, with these verdicts."""
    written = MOCK_NBA_REPORT.model_dump(include={"situation", "focus", "moves", "strategy"})
    return ScoutAnswer.model_validate({**written, "verdicts": [v.model_dump() for v in verdicts]})


def _verdict(position: int, decision: Any = "AGREE") -> VerdictAnswer:
    return VerdictAnswer(task=task_id(position), decision=decision, reason="because")


def _judged(report: ScoutReport) -> list[str]:
    return [t.verdict.task for t in report.tasks if t.verdict]


def _run(report: ScoutAnswer, tasks: list[Action] = TASKS) -> ScoutReport:
    engine = ScoutEngine(ContextOnly(tasks), key="nfl-sleeper", ai=FakeAI(report=report), answers=FakeAnswers())
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

    assert _judged(report) == [task_id(1)]


def test_only_the_first_of_two_verdicts_on_one_task_counts() -> None:
    """Two would contradict each other beside the same row."""
    report = _run(_report(_verdict(1, "AGREE"), _verdict(1, "OVERRULE")))

    assert report.tasks[0].verdict is not None and report.tasks[0].verdict.decision == "AGREE"


def test_the_moves_are_the_models_and_the_tasks_the_providers() -> None:
    report = _run(_report())

    assert [m.player for m in report.moves] == [m.player for m in MOCK_NBA_REPORT.moves]
    assert [t.player_id for t in report.tasks] == ["a", "c"]


def test_a_competition_with_no_tasks_reports_none() -> None:
    report = _run(_report(_verdict(1)), tasks=[])

    assert report.tasks == []


def test_the_headline_still_comes_from_the_provider() -> None:
    assert [s.label for s in _run(_report()).headline] == ["Week"]


# ── keeping the judgment ────────────────────────────────────────────────


def test_an_unchanged_week_is_answered_from_the_last_judgment_without_a_call() -> None:
    """On a free tier a call is the scarce thing, and the answer would be the same."""
    ai, answers = FakeAI(report=_report(_verdict(1))), FakeAnswers()
    engine = ScoutEngine(ContextOnly(TASKS), key="nfl-sleeper", ai=ai, answers=answers)

    first, _ = engine.start_analysis("L1")
    second, _ = engine.start_analysis("L1")

    assert len(ai.prompts) == 1
    assert second == first


def test_a_changed_week_is_judged_afresh_and_kept() -> None:
    ai, answers = FakeAI(report=_report(_verdict(1))), FakeAnswers()
    ScoutEngine(ContextOnly(TASKS, prompt="monday"), key="nfl-sleeper", ai=ai, answers=answers).start_analysis("L1")

    engine = ScoutEngine(ContextOnly(TASKS, prompt="tuesday"), key="nfl-sleeper", ai=ai, answers=answers)
    engine.start_analysis("L1")

    assert ai.prompts == ["monday", "tuesday"]
    latest = engine.latest("L1")
    assert latest is not None and latest.answer.tasks[0].verdict is not None


def test_judgments_are_kept_per_league() -> None:
    ai, answers = FakeAI(report=_report()), FakeAnswers()
    engine = ScoutEngine(ContextOnly(TASKS), key="nfl-sleeper", ai=ai, answers=answers)

    engine.start_analysis("L1")

    assert engine.latest("L2") is None


# ── moves the model suggests ────────────────────────────────────────────


def _suggesting(*moves: tuple[str, str]) -> ScoutAnswer:
    """The mock report with these ADDs in place of its moves, each (added, dropped)."""
    written = MOCK_NBA_REPORT.model_dump(include={"situation", "focus", "strategy"})
    return ScoutAnswer.model_validate(
        {
            **written,
            "moves": [
                {
                    "action": "ADD",
                    "player": added,
                    "position": "WR",
                    "team": "ATL",
                    "metric": "8.7 proj pts",
                    "rationale": "why",
                    "replaces": dropped,
                }
                for added, dropped in moves
            ],
        }
    )


def _moves_kept(answer: ScoutAnswer, worth: dict[str, float]) -> list[str]:
    provider = ContextOnly(TASKS)
    provider.context.worth = worth
    engine = ScoutEngine(provider, key="nfl-sleeper", ai=FakeAI(report=answer), answers=FakeAnswers())
    return [m.player for m in engine.report("L1").moves]


def test_an_add_worth_less_a_game_than_the_player_it_drops_is_not_suggested() -> None:
    """A player on bye reads as nothing this week; the season says what he is worth."""
    answer = _suggesting(("Jahan Dotson (WR, ATL)", "Germie Bernard"))

    assert _moves_kept(answer, {"Jahan Dotson": 7.5, "Germie Bernard": 8.4}) == []


def test_an_add_worth_more_than_his_drop_stands() -> None:
    answer = _suggesting(("Jahan Dotson", "Germie Bernard"))

    assert _moves_kept(answer, {"Jahan Dotson": 9.0, "Germie Bernard": 8.4}) == ["Jahan Dotson"]


def test_a_move_naming_a_player_of_unknown_worth_stands() -> None:
    """A streamed position, or a competition that sends no worth: nothing to weigh it by."""
    answer = _suggesting(("New Orleans Saints", "Cincinnati Bengals"))

    assert _moves_kept(answer, {}) == ["New Orleans Saints"]


def _judged_then(answer: ScoutAnswer, judged_on: dict[str, float], **now: Any) -> list[str]:
    """The kept judgment's moves as the page reads them back once the week has moved on to `now`."""
    provider = ContextOnly(TASKS)
    provider.context.worth = judged_on
    engine = ScoutEngine(provider, key="nfl-sleeper", ai=FakeAI(report=answer), answers=FakeAnswers())
    engine.report("L1")
    provider.context = replace(provider.context, prompt="later", **now)
    latest = engine.latest("L1")
    assert latest is not None
    return [m.player for m in latest.answer.moves]


SUGGESTED = _suggesting(("Jahan Dotson", "Germie Bernard"))


def test_a_kept_move_for_a_game_already_played_is_not_shown() -> None:
    assert _judged_then(SUGGESTED, {}, movable=frozenset({"Germie Bernard"})) == []


def test_a_kept_move_everyone_in_can_still_make_is_shown() -> None:
    movable = frozenset({"Jahan Dotson", "Germie Bernard"})
    assert _judged_then(SUGGESTED, {}, movable=movable) == ["Jahan Dotson"]


def test_a_kept_move_a_rule_added_since_would_strike_is_not_shown() -> None:
    assert _judged_then(SUGGESTED, {}, worth={"Jahan Dotson": 7.5, "Germie Bernard": 8.4}) == []


def test_a_competition_that_names_no_movable_players_keeps_every_move() -> None:
    assert _judged_then(SUGGESTED, {}) == ["Jahan Dotson"]


class Unreachable(ContextOnly):
    """A provider whose week will not load once the judgment is kept."""

    down = False

    def build_context(self, league_id: str) -> CompetitionContext:
        if self.down:
            raise PlatformError("Sleeper is down")
        return self.context


def test_a_week_that_will_not_load_shows_the_kept_moves_unchecked() -> None:
    provider = Unreachable(TASKS)
    engine = ScoutEngine(provider, key="nfl-sleeper", ai=FakeAI(report=SUGGESTED), answers=FakeAnswers())
    engine.report("L1")
    provider.down = True

    latest = engine.latest("L1")

    assert latest is not None and [m.player for m in latest.answer.moves] == ["Jahan Dotson"]
