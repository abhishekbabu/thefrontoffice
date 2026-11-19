"""Tests for the to-do list as a model reads it: `competitions/tasks.py`."""

from thefrontoffice.adapters.outbound.competitions.tasks import task_lines
from thefrontoffice.domain.models import Action, task_id


def _item(title: str, when: str = "") -> Action:
    return Action(kind="lineup", urgency="soon", title=title, reason="Why.", when=when)


def test_each_item_is_numbered_by_the_id_a_verdict_names_it_by() -> None:
    lines = task_lines([_item("Start A"), _item("Start B", when="first")]).splitlines()

    assert lines[0].startswith(f"- {task_id(1)} ")
    assert "Start A" in lines[0]
    assert lines[1].startswith(f"- {task_id(2)} ")
    assert "(first)" in lines[1]


def test_no_items_is_no_lines() -> None:
    assert task_lines([]) == ""
