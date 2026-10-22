"""Tests for calls on the free agents on screen: `application/wire.py`.

The provider is a stand-in whose per-player lines a test can change, which
is what makes a kept call current or stale; the model returns whatever calls
the test scripts, and records each prompt it was asked.
"""

from typing import Any

from conftest import FakeAI, FakeAnswers

from thefrontoffice.application.wire import MAX_JUDGED, WireEngine
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import CompetitionContext, PlayerCall, WireReport


class Wire:
    label = "NFL (Sleeper)"
    sport = "football"

    def __init__(self) -> None:
        self.lines: dict[str, str] = {}
        self.asked: list[list[str]] = []
        self.claimed: set[str] = set()

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        self.asked.append(player_ids)
        claimed = [pid for pid in player_ids if pid in self.claimed]
        if claimed:
            raise PlayerNotFoundError(claimed)
        targets = {pid: self.lines.get(pid, f"{pid}: 9.0 proj pts") for pid in player_ids}
        return CompetitionContext(prompt="\n".join(targets.values()), targets=targets)


class Scripted(FakeAI):
    """A model answering each prompt with a call on every player in it, unless told otherwise."""

    def __init__(self, *calls: PlayerCall) -> None:
        super().__init__()
        self.calls = list(calls)

    def generate_structured(self, prompt: str, schema: type, mock: Any = None) -> Any:
        self.prompts.append(prompt)
        if self.calls:
            return WireReport(calls=self.calls)
        ids = [line.split(":")[0] for line in prompt.splitlines()]
        return WireReport(calls=[_call(pid) for pid in ids])


def _call(pid: str, decision: Any = "ADD") -> PlayerCall:
    return PlayerCall(player_id=pid, decision=decision, reason=f"because of {pid}")


def _engine(ai: FakeAI | None = None, answers: FakeAnswers | None = None) -> tuple[WireEngine, Wire, FakeAI]:
    wire, model = Wire(), ai or Scripted()
    return WireEngine(wire, ai=model, answers=answers or FakeAnswers()), wire, model  # type: ignore[arg-type]


# ── what comes back ─────────────────────────────────────────────────────


def test_calls_come_back_in_the_order_the_players_were_asked_about() -> None:
    engine, _, _ = _engine(Scripted(_call("b", "PASS"), _call("a")))

    assert [c.player_id for c in engine.judge("L1", ["a", "b"])] == ["a", "b"]


def test_a_call_on_someone_not_asked_about_is_dropped() -> None:
    """It would have no row to sit on."""
    engine, _, _ = _engine(Scripted(_call("a"), _call("zz")))

    assert [c.player_id for c in engine.judge("L1", ["a"])] == ["a"]


def test_only_the_first_of_two_calls_on_one_player_counts() -> None:
    engine, _, _ = _engine(Scripted(_call("a", "ADD"), _call("a", "PASS")))

    assert [c.decision for c in engine.judge("L1", ["a"])] == ["ADD"]


def test_a_player_the_model_skipped_has_no_call() -> None:
    engine, _, _ = _engine(Scripted(_call("a")))

    assert [c.player_id for c in engine.judge("L1", ["a", "b"])] == ["a"]


def test_no_more_than_a_screen_of_players_is_put_to_the_model() -> None:
    engine, wire, _ = _engine()
    ids = [f"p{i}" for i in range(MAX_JUDGED + 5)]

    engine.judge("L1", ids)

    assert wire.asked[-1] == ids[:MAX_JUDGED]


def test_a_player_listed_twice_is_asked_about_once() -> None:
    engine, wire, _ = _engine()

    engine.judge("L1", ["a", "a", "b"])

    assert wire.asked[-1] == ["a", "b"]


def test_a_fresh_call_says_when_it_was_made_and_is_not_stale() -> None:
    engine, _, _ = _engine()

    [call] = engine.judge("L1", ["a"])

    assert call.judged_at is not None and not call.stale


# ── keeping calls ───────────────────────────────────────────────────────


def test_judging_again_asks_only_about_players_whose_situation_moved() -> None:
    engine, wire, model = _engine()
    engine.judge("L1", ["a", "b"])
    wire.lines["b"] = "b: 14.0 proj pts, now the lead back"

    calls = engine.judge("L1", ["a", "b"])

    assert len(model.prompts) == 2
    assert "a:" not in model.prompts[-1] and "b:" in model.prompts[-1]
    assert [c.player_id for c in calls] == ["a", "b"]


def test_judging_an_unchanged_page_again_costs_no_call() -> None:
    engine, _, model = _engine()
    engine.judge("L1", ["a", "b"])

    engine.judge("L1", ["a", "b"])

    assert len(model.prompts) == 1


def test_kept_calls_are_shown_without_asking_the_model() -> None:
    engine, _, model = _engine()
    engine.judge("L1", ["a"])

    [call] = engine.kept("L1", ["a", "b"])

    assert call.player_id == "a" and not call.stale
    assert len(model.prompts) == 1


def test_a_kept_call_on_a_player_whose_situation_moved_is_shown_stale() -> None:
    engine, wire, _ = _engine()
    engine.judge("L1", ["a"])
    wire.lines["a"] = "a: ruled out"

    [call] = engine.kept("L1", ["a"])

    assert call.stale


def test_calls_are_kept_per_league() -> None:
    answers = FakeAnswers()
    engine, _, _ = _engine(answers=answers)
    engine.judge("L1", ["a"])

    assert engine.kept("L2", ["a"]) == []


def test_a_player_claimed_since_the_page_loaded_is_skipped_not_fatal() -> None:
    """One player gone from the wire should not cost every other row its call."""
    engine, wire, _ = _engine()
    engine.judge("L1", ["a", "b"])
    wire.claimed.add("a")

    assert [c.player_id for c in engine.kept("L1", ["a", "b"])] == ["b"]
    assert [c.player_id for c in engine.judge("L1", ["a", "b"])] == ["b"]


def test_a_page_whose_every_player_has_gone_has_no_calls() -> None:
    engine, wire, _ = _engine()
    wire.claimed.update({"a", "b"})

    assert engine.kept("L1", ["a", "b"]) == []
