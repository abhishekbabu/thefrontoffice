"""Tests for keeping model answers on disk: `storage/answers.py`."""

from datetime import UTC, datetime
from pathlib import Path

from support.reports import MOCK_FPL_REPORT

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.answers import DiskAnswerStore
from thefrontoffice.domain.models import Action, Remembered, ScoutReport, TaskVerdict

TASK = Action(
    kind="lineup",
    urgency="now",
    title="Start A over B",
    reason="B is out.",
    key="hole:b",
    verdict=TaskVerdict(task="T1", decision="AGREE", reason="A is the starter now."),
)


def _kept(answer: object) -> Remembered:
    return Remembered(answer=answer, answered_at=datetime.now(UTC), inputs="abc")


def test_a_report_survives_the_round_trip_through_the_file(tmp_path: Path) -> None:
    DiskAnswerStore(DiskCache(tmp_path)).save(
        "scout:NFL:L1", _kept(MOCK_FPL_REPORT.model_copy(update={"tasks": [TASK]}))
    )

    # A fresh store on the same directory: what a restarted server reads.
    loaded = DiskAnswerStore(DiskCache(tmp_path)).latest("scout:NFL:L1", ScoutReport)

    assert loaded is not None and loaded.inputs == "abc"
    [task] = loaded.answer.tasks
    assert task.verdict == TASK.verdict
    # What the verdict judged reads back the same, or every row would look stale.
    assert task.fingerprint == TASK.fingerprint


def test_an_answer_kept_under_the_competitions_label_is_found_under_its_key(tmp_path: Path) -> None:
    """Judgments were once filed under the label: the week's verdicts survive keying them by entry."""
    DiskAnswerStore(DiskCache(tmp_path)).save("scout:NFL (Sleeper):L1", _kept(MOCK_FPL_REPORT))

    loaded = DiskAnswerStore(DiskCache(tmp_path)).latest("scout:nfl-sleeper:L1", ScoutReport)

    assert loaded is not None and loaded.answer == MOCK_FPL_REPORT
