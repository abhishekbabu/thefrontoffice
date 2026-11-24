"""Tests for the players the manager will not let go: `application/untouchables.py`."""

import pytest
from pydantic import ValidationError
from support.stores import FakeUntouchableStore

from thefrontoffice.application.untouchables import UntouchableMarks
from thefrontoffice.domain.models import UntouchableMark, Untouchables


def _marks(store: FakeUntouchableStore | None = None, key: str = "nfl-sleeper") -> UntouchableMarks:
    return UntouchableMarks(store or FakeUntouchableStore(), key)


def test_a_league_with_nobody_marked_has_no_untouchables() -> None:
    marks = _marks()

    assert marks.of("L1") == frozenset()
    assert marks.listed("L1") == Untouchables()


def test_a_marked_player_is_untouchable_in_his_league_alone() -> None:
    marks = _marks()

    answered = marks.mark("L1", UntouchableMark(player_id="4881", untouchable=True))

    assert answered.player_ids == ["4881"]
    assert marks.of("L1") == {"4881"}
    assert marks.of("L2") == frozenset()


def test_marks_are_kept_per_competition() -> None:
    """The same league id on another platform is another league."""
    store = FakeUntouchableStore()
    _marks(store, "nfl-sleeper").mark("L1", UntouchableMark(player_id="4881", untouchable=True))

    assert _marks(store, "nba-yahoo").of("L1") == frozenset()


def test_marking_twice_keeps_him_once_and_clearing_leaves_the_rest_in_order() -> None:
    marks = _marks()
    for pid in ("a", "b", "a", "c"):
        marks.mark("L1", UntouchableMark(player_id=pid, untouchable=True))

    assert marks.listed("L1").player_ids == ["b", "a", "c"]
    assert marks.mark("L1", UntouchableMark(player_id="a", untouchable=False)).player_ids == ["b", "c"]


def test_clearing_a_player_never_marked_changes_nothing() -> None:
    marks = _marks()
    marks.mark("L1", UntouchableMark(player_id="a", untouchable=True))

    assert marks.mark("L1", UntouchableMark(player_id="z", untouchable=False)).player_ids == ["a"]


def test_a_mark_has_to_name_a_player() -> None:
    with pytest.raises(ValidationError):
        UntouchableMark(player_id="", untouchable=True)
