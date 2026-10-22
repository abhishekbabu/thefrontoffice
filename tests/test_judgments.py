"""Tests for keeping each league's latest judgment on disk: `llm/judgments.py`."""

from datetime import datetime, timezone
from pathlib import Path

from reports import MOCK_FPL_REPORT

from thefrontoffice.adapters.outbound.llm.judgments import DiskJudgmentStore
from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.domain.models import Action, Judgment, TaskVerdict

TASK = Action(
    kind="lineup",
    urgency="now",
    title="Start A over B",
    reason="B is out.",
    key="hole:b",
    verdict=TaskVerdict(task="T1", decision="AGREE", reason="A is the starter now."),
)


def _judgment() -> Judgment:
    report = MOCK_FPL_REPORT.model_copy(update={"tasks": [TASK]})
    return Judgment(report=report, judged_at=datetime.now(timezone.utc), inputs="abc")


def test_a_judgment_survives_the_round_trip_through_the_file(tmp_path: Path) -> None:
    store = DiskJudgmentStore(JsonDiskCache(tmp_path))
    store.save("NFL (Sleeper):L1", _judgment())

    # A fresh store on the same directory: what a restarted server reads.
    loaded = DiskJudgmentStore(JsonDiskCache(tmp_path)).latest("NFL (Sleeper):L1")

    assert loaded is not None
    assert loaded.inputs == "abc"
    [task] = loaded.report.tasks
    assert task.verdict == TASK.verdict
    # What the verdict judged reads back the same, or every row would look stale.
    assert task.fingerprint == TASK.fingerprint


def test_each_league_keeps_its_own(tmp_path: Path) -> None:
    store = DiskJudgmentStore(JsonDiskCache(tmp_path))
    store.save("NFL (Sleeper):L1", _judgment())

    assert store.latest("NFL (Sleeper):L2") is None
