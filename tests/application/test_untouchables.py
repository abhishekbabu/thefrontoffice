"""Tests for the players the manager will not let go: `application/untouchables.py`."""

import pytest
from pydantic import ValidationError
from support.stores import FakeUntouchableStore

from thefrontoffice.application.untouchables import UntouchableMarks
from thefrontoffice.domain.errors import PlatformError
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


# ── one squad, every league ─────────────────────────────────────────────


def _squad(store: FakeUntouchableStore) -> UntouchableMarks:
    return UntouchableMarks(store, "premier-league-fpl", squad=lambda _: "42")


def test_a_mark_on_a_squad_holds_in_every_league_it_plays() -> None:
    store = FakeUntouchableStore()
    _squad(store).mark("L1", UntouchableMark(player_id="7", untouchable=True))

    assert _squad(store).of("L2") == {"7"}
    assert _squad(store).mark("L3", UntouchableMark(player_id="7", untouchable=False)).player_ids == []
    assert _squad(store).of("L1") == frozenset()


def test_marks_kept_per_league_move_onto_the_squad_when_their_league_is_read() -> None:
    store = FakeUntouchableStore()
    _marks(store, "premier-league-fpl").mark("L1", UntouchableMark(player_id="7", untouchable=True))
    _marks(store, "premier-league-fpl").mark("L2", UntouchableMark(player_id="9", untouchable=True))
    _squad(store).mark("L3", UntouchableMark(player_id="3", untouchable=True))

    assert _squad(store).listed("L1").player_ids == ["3", "7"]
    assert _squad(store).listed("L2").player_ids == ["3", "7", "9"]
    # Moved, not copied: clearing one on the squad does not bring the league's copy back.
    _squad(store).mark("L1", UntouchableMark(player_id="7", untouchable=False))
    assert _squad(store).of("L1") == {"3", "9"}


# ── players who have left ───────────────────────────────────────────────


def test_a_mark_on_a_player_no_longer_held_is_dropped_when_listed_against_the_roster() -> None:
    marks = _marks()
    for pid in ("a", "b"):
        marks.mark("L1", UntouchableMark(player_id=pid, untouchable=True))

    assert marks.listed("L1", lambda: ["b", "c"]).player_ids == ["b"]
    assert marks.of("L1") == {"b"}


def test_a_roster_that_fails_or_reads_empty_drops_nothing() -> None:
    marks = _marks()
    marks.mark("L1", UntouchableMark(player_id="a", untouchable=True))

    def down() -> list[str]:
        raise PlatformError("down")

    assert marks.listed("L1", down).player_ids == ["a"]
    assert marks.listed("L1", list).player_ids == ["a"]


def test_with_nobody_marked_the_roster_is_not_read() -> None:
    def unread() -> list[str]:
        raise AssertionError("read")

    assert _marks().listed("L1", unread).player_ids == []
