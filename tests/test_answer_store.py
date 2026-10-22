"""Tests for keeping model answers on disk: `llm/answers.py`."""

from datetime import datetime, timezone
from pathlib import Path

from reports import MOCK_FPL_REPORT

from thefrontoffice.adapters.outbound.llm.answers import DiskAnswerStore
from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.domain.models import Action, PlayerCall, Remembered, ScoutReport, TaskVerdict

TASK = Action(
    kind="lineup",
    urgency="now",
    title="Start A over B",
    reason="B is out.",
    key="hole:b",
    verdict=TaskVerdict(task="T1", decision="AGREE", reason="A is the starter now."),
)


def _kept(answer: object) -> Remembered:  # type: ignore[type-arg]
    return Remembered(answer=answer, answered_at=datetime.now(timezone.utc), inputs="abc")  # type: ignore[arg-type]


def test_a_report_survives_the_round_trip_through_the_file(tmp_path: Path) -> None:
    DiskAnswerStore(JsonDiskCache(tmp_path)).save(
        "scout:NFL:L1", _kept(MOCK_FPL_REPORT.model_copy(update={"tasks": [TASK]}))
    )

    # A fresh store on the same directory: what a restarted server reads.
    loaded = DiskAnswerStore(JsonDiskCache(tmp_path)).latest("scout:NFL:L1", ScoutReport)

    assert loaded is not None and loaded.inputs == "abc"
    [task] = loaded.answer.tasks
    assert task.verdict == TASK.verdict
    # What the verdict judged reads back the same, or every row would look stale.
    assert task.fingerprint == TASK.fingerprint


def test_any_answer_shape_is_kept_the_same_way(tmp_path: Path) -> None:
    call = PlayerCall(player_id="8155", decision="WATCH", reason="His role is growing.")
    store = DiskAnswerStore(JsonDiskCache(tmp_path))
    store.save("wire:NFL:L1:8155", _kept(call))

    loaded = store.latest("wire:NFL:L1:8155", PlayerCall)

    assert loaded is not None and loaded.answer == call


def test_each_scope_keeps_its_own(tmp_path: Path) -> None:
    store = DiskAnswerStore(JsonDiskCache(tmp_path))
    store.save("scout:NFL:L1", _kept(MOCK_FPL_REPORT))

    assert store.latest("scout:NFL:L2", ScoutReport) is None
