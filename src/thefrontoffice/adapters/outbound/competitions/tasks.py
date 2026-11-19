"""The week's to-do list as a model reads it: numbered, so a verdict can name the item it judges."""

from collections.abc import Sequence

from thefrontoffice.domain.models import Action, task_id


def task_line(position: int, task: Action) -> str:
    """One to-do item as the model reads it: its id, the move, why, who it moves and where each stands, and what it rests on."""
    when = f" ({task.when})" if task.when else ""
    evidence = "".join(f"    {line}\n" for line in task.lines())
    return f"- {task_id(position)} [{task.urgency}, {task.kind}] {task.title}{when}. {task.reason}\n{evidence}"


def task_lines(tasks: Sequence[Action]) -> str:
    """Every item, numbered from 1 in the order given (`task_id`); empty for none."""
    return "".join(task_line(i, task) for i, task in enumerate(tasks, start=1))
