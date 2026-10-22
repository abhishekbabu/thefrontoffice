"""Tests for calls on the free agents on screen: `application/wire.py`."""

from typing import Any

from conftest import FakeAI

from thefrontoffice.application.wire import MAX_JUDGED, WireEngine
from thefrontoffice.domain.models import CompetitionContext, PlayerCall, WireReport


class Wire:
    label = "NFL (Sleeper)"
    sport = "football"

    def __init__(self) -> None:
        self.asked: list[str] = []

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        self.asked = player_ids
        return CompetitionContext(prompt="wire")


def _call(pid: str, decision: Any = "ADD") -> PlayerCall:
    return PlayerCall(player_id=pid, decision=decision, reason="because")


def _judge(asked: list[str], *calls: PlayerCall) -> tuple[list[PlayerCall], Wire]:
    wire = Wire()
    engine = WireEngine(wire, ai=FakeAI(report=WireReport(calls=list(calls))))  # type: ignore[arg-type]
    return engine.judge("L1", asked), wire


def test_calls_come_back_in_the_order_the_players_were_asked_about() -> None:
    calls, _ = _judge(["a", "b"], _call("b", "PASS"), _call("a"))

    assert [c.player_id for c in calls] == ["a", "b"]


def test_a_call_on_someone_not_asked_about_is_dropped() -> None:
    """It would have no row to sit on."""
    calls, _ = _judge(["a"], _call("a"), _call("zz"))

    assert [c.player_id for c in calls] == ["a"]


def test_only_the_first_of_two_calls_on_one_player_counts() -> None:
    calls, _ = _judge(["a"], _call("a", "ADD"), _call("a", "PASS"))

    assert [c.decision for c in calls] == ["ADD"]


def test_a_player_the_model_skipped_has_no_call() -> None:
    calls, _ = _judge(["a", "b"], _call("a"))

    assert [c.player_id for c in calls] == ["a"]


def test_no_more_than_a_screen_of_players_is_put_to_the_model() -> None:
    ids = [f"p{i}" for i in range(MAX_JUDGED + 5)]

    _, wire = _judge(ids)

    assert wire.asked == ids[:MAX_JUDGED]


def test_a_player_listed_twice_is_asked_about_once() -> None:
    _, wire = _judge(["a", "a", "b"])

    assert wire.asked == ["a", "b"]
