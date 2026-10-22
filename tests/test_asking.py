"""Tests for questions asked of one thing on screen: `application/asking.py`.

The provider is a stand-in with one to-do item and one player; the model is
the conftest fake, whose chat records what was sent.
"""

from datetime import datetime, timezone

import pytest
from conftest import FakeAI, FakeAnswers
from reports import MOCK_FPL_REPORT

from thefrontoffice.application.asking import AskEngine
from thefrontoffice.application.scouting import scout_scope
from thefrontoffice.domain.errors import SubjectGoneError
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    PlayerCard,
    PlayerDetail,
    Remembered,
    Stat,
    StatGroup,
    Subject,
    TaskVerdict,
)

TASK = Action(
    kind="lineup",
    urgency="soon",
    title="Start Breece Hall over Germie Bernard",
    reason="+2.5 proj pts.",
    when="before kickoff, Sun 25 Oct",
    key="swap:hall:bernard",
    evidence=[Stat(label="Breece Hall", value="vs MIA, 4th-most to RBs (26.1 a game)")],
)

HALL = PlayerDetail(
    player_id="hall",
    name="Breece Hall",
    position="RB",
    team="NYJ",
    groups=[StatGroup(title="Role and matchup", stats=[Stat(label="Snap share, last 3", value="57%")])],
)


class OneWeek:
    competition = "nfl"
    label = "NFL (Sleeper)"

    def build_context(self, league_id: str) -> CompetitionContext:
        return CompetitionContext(
            prompt="prompt",
            situation="SITUATION: 3-3, chasing.",
            roster_lines={"Breece Hall": "- Breece Hall (RB, NYJ) vs MIA: 14.1 proj pts\n"},
            tasks=[TASK],
        )

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        return HALL

    def roster(self, league_id: str) -> list[PlayerCard]:
        return [PlayerCard(player_id="gibbs", columns={"Player": "Jahmyr Gibbs", "Pos": "RB"})]


def _ask(subject: Subject, *questions: str, answers: FakeAnswers | None = None) -> list[str]:
    ai = FakeAI()
    chat = AskEngine(OneWeek(), ai=ai, answers=answers or FakeAnswers()).open("L1", subject)  # type: ignore[arg-type]
    for question in questions:
        chat.send_message(question)
    return ai.chat.sent


def test_a_question_about_an_item_carries_the_item_its_evidence_and_the_roster() -> None:
    [sent] = _ask(Subject(kind="task", key=TASK.key), "Why?")

    assert TASK.title in sent and TASK.when in sent
    assert all(line.value in sent for line in TASK.evidence)
    assert "Breece Hall (RB, NYJ)" in sent
    assert sent.endswith("Why?")


def test_only_the_first_question_carries_the_briefing() -> None:
    """Every turn resends the history; the briefing is in it once already."""
    first, second = _ask(Subject(kind="task", key=TASK.key), "Why?", "And if he sits?")

    assert TASK.title in first
    assert second == "And if he sits?"


def test_an_earlier_verdict_on_the_item_is_part_of_the_conversation() -> None:
    judged = TASK.model_copy(
        update={"verdict": TaskVerdict(task="T1", decision="WAIT", reason="His status is due Sunday.")}
    )
    answers = FakeAnswers()
    answers.save(
        scout_scope(OneWeek.label, "L1"),
        Remembered(
            answer=MOCK_FPL_REPORT.model_copy(update={"tasks": [judged]}),
            answered_at=datetime.now(timezone.utc),
            inputs="x",
        ),
    )

    [sent] = _ask(Subject(kind="task", key=TASK.key), "Why wait?", answers=answers)

    assert "His status is due Sunday." in sent


def test_an_item_the_week_no_longer_holds_is_said_to_be_gone() -> None:
    with pytest.raises(SubjectGoneError):
        _ask(Subject(kind="task", key="swap:someone:else"), "Why?")


def test_a_question_about_a_player_carries_what_the_drawer_shows_and_the_roster() -> None:
    [sent] = _ask(Subject(kind="player", key="hall"), "Is he the lead back?")

    assert HALL.name in sent
    assert "57%" in sent
    assert "Jahmyr Gibbs" in sent
