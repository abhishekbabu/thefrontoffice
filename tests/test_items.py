"""Tests for the manager's decisions about to-do items: `application/items.py`."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import FakeItemStates
from pydantic import ValidationError

from thefrontoffice.application.items import ItemDecisions, apply_decisions
from thefrontoffice.domain.errors import ItemDecisionError
from thefrontoffice.domain.models import Action, ItemDecision, ItemState

NOW = datetime(2026, 10, 22, 18, tzinfo=timezone.utc)

SWAP = Action(kind="lineup", urgency="soon", title="Start A over B", reason="+2.5 proj pts.", key="swap:a:b")
BYE = Action(kind="waiver", urgency="later", title="Find a RB for week 8", reason="A is on bye.", key="bye:8:RB")


def _marked(states: dict[str, ItemState], *actions: Action) -> list[Action]:
    return apply_decisions(list(actions or (SWAP, BYE)), states, NOW)


# ── applying decisions ──────────────────────────────────────────────────


def test_an_item_with_no_decision_is_left_as_it_is() -> None:
    assert _marked({}) == [SWAP, BYE]


def test_a_dismissed_item_is_hidden_while_it_reads_as_it_did() -> None:
    [swap, bye] = _marked({SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    assert swap.hidden == "dismissed"
    assert bye.hidden is None


def test_a_dismissed_item_that_has_changed_comes_back_saying_so() -> None:
    """New news or a different gain is new information, which a dismissal of the old item did not weigh."""
    changed = SWAP.model_copy(update={"reason": "+6.0 proj pts."})

    [swap] = _marked({SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)}, changed)

    assert swap.hidden is None and swap.resurfaced


def test_a_snoozed_item_is_hidden_until_its_time() -> None:
    until = NOW + timedelta(hours=3)

    [swap] = _marked({SWAP.key: ItemState(key=SWAP.key, snoozed_until=until)}, SWAP)

    assert (swap.hidden, swap.snoozed_until) == ("snoozed", until)


def test_a_snooze_that_has_run_out_hides_nothing() -> None:
    [swap] = _marked({SWAP.key: ItemState(key=SWAP.key, snoozed_until=NOW - timedelta(minutes=1))}, SWAP)

    assert swap.hidden is None


def test_the_order_of_the_list_is_kept() -> None:
    """Most urgent first is the list's own order; hiding one does not reshuffle the rest."""
    marked = _marked({SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    assert [a.key for a in marked] == [SWAP.key, BYE.key]


# ── keeping decisions ───────────────────────────────────────────────────


def _decisions() -> tuple[ItemDecisions, FakeItemStates]:
    store = FakeItemStates()
    return ItemDecisions(store, clock=lambda: NOW), store


def test_a_dismissal_is_kept_against_the_item_as_it_read() -> None:
    decisions, _ = _decisions()

    decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="dismiss", fingerprint=SWAP.fingerprint))

    [swap, _bye] = decisions.apply("NFL", "L1", [SWAP, BYE])
    assert swap.hidden == "dismissed"


def test_a_later_decision_replaces_an_earlier_one() -> None:
    decisions, _ = _decisions()
    decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="dismiss", fingerprint=SWAP.fingerprint))

    decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="snooze", until=NOW + timedelta(hours=1)))

    [swap] = decisions.apply("NFL", "L1", [SWAP])
    assert swap.hidden == "snoozed"


def test_restoring_forgets_the_decision() -> None:
    decisions, _ = _decisions()
    decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="dismiss", fingerprint=SWAP.fingerprint))

    assert decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="restore")) is None
    assert decisions.apply("NFL", "L1", [SWAP]) == [SWAP]


def test_a_snooze_is_kept_in_utc_whatever_offset_it_arrived_with() -> None:
    decisions, _ = _decisions()
    pacific = timezone(timedelta(hours=-7))

    state = decisions.decide(
        "NFL", "L1", ItemDecision(key=SWAP.key, decision="snooze", until=datetime(2026, 10, 23, 8, tzinfo=pacific))
    )

    assert state is not None and state.snoozed_until == datetime(2026, 10, 23, 15, tzinfo=timezone.utc)


def test_a_snooze_into_the_past_is_refused() -> None:
    decisions, _ = _decisions()

    with pytest.raises(ItemDecisionError):
        decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="snooze", until=NOW - timedelta(hours=1)))


def test_decisions_are_kept_per_league() -> None:
    decisions, _ = _decisions()
    decisions.decide("NFL", "L1", ItemDecision(key=SWAP.key, decision="dismiss", fingerprint=SWAP.fingerprint))

    assert decisions.apply("NFL", "L2", [SWAP]) == [SWAP]


# ── what a decision must say ────────────────────────────────────────────


def test_a_dismissal_must_name_what_it_dismissed() -> None:
    with pytest.raises(ValidationError):
        ItemDecision(key="k", decision="dismiss")


def test_a_snooze_must_say_when_it_ends_with_an_offset() -> None:
    for until in (None, datetime(2026, 10, 23, 8)):
        with pytest.raises(ValidationError):
            ItemDecision(key="k", decision="snooze", until=until)
