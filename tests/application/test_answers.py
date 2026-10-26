"""Tests for keeping model answers: `application/answers.py`."""

from datetime import UTC, datetime

from pydantic import BaseModel
from support.stores import FakeAnswers

from thefrontoffice.application.answers import Answers, is_current


class Note(BaseModel):
    text: str


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 22, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_an_unchanged_input_is_answered_from_what_was_kept() -> None:
    answers, asked = Answers(FakeAnswers()), []

    def ask() -> Note:
        asked.append(1)
        return Note(text=f"answer {len(asked)}")

    first = answers.answer("scope", "same input", Note, ask)
    second = answers.answer("scope", "same input", Note, ask)

    assert (first.answer, second.answer) == (Note(text="answer 1"), Note(text="answer 1"))
    assert len(asked) == 1


def test_a_changed_input_is_asked_again_and_replaces_what_was_kept() -> None:
    answers = Answers(FakeAnswers())
    answers.answer("scope", "monday", Note, lambda: Note(text="monday's"))

    fresh = answers.answer("scope", "tuesday", Note, lambda: Note(text="tuesday's"))

    kept = answers.latest("scope", Note)
    assert fresh.answer.text == "tuesday's"
    assert kept is not None and kept.answer.text == "tuesday's"


def test_the_kept_answer_says_what_it_answered_and_when() -> None:
    clock = Clock()
    answers = Answers(FakeAnswers(), clock=clock)

    kept = answers.keep("scope", "the input", Note(text="x"))

    assert kept.answered_at == clock.now
    assert is_current(kept, "the input")
    assert not is_current(kept, "another input")


def test_scopes_keep_their_answers_apart() -> None:
    answers = Answers(FakeAnswers())
    answers.keep("one", "input", Note(text="one's"))

    assert answers.latest("two", Note) is None
