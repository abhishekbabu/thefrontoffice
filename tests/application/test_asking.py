"""Tests for questions asked of one thing on screen: `application/asking.py`.

The provider is a stand-in with one to-do item and one player; the model is
the conftest fake, whose chat records what was sent.
"""

from datetime import UTC, datetime

import pytest
from support.ai import FakeAI
from support.reports import MOCK_FPL_REPORT
from support.stores import FakeAnswers

from thefrontoffice.application.asking import AskEngine
from thefrontoffice.application.scouting import scout_scope
from thefrontoffice.domain.errors import SubjectGoneError
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    Remembered,
    StandingRow,
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

    def schedule(self, league_id: str) -> LeagueSchedule:
        return LeagueSchedule(
            standings=[
                StandingRow(rank=1, name="Shawoozals", record="6-1"),
                StandingRow(rank=9, name="abhibeast", record="3-4", is_mine=True),
            ]
        )

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        coleman = PlayerCard(player_id="coleman", columns={"Player": "Jonah Coleman", "Pos": "RB"})
        return PlayerPage(players=[coleman], total=412)


def _ask(subject: Subject, *questions: str, answers: FakeAnswers | None = None) -> list[str]:
    ai = FakeAI()
    chat = AskEngine(OneWeek(), ai=ai, answers=answers or FakeAnswers()).open("L1", subject)
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
            answered_at=datetime.now(UTC),
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


def test_a_thread_about_a_page_carries_what_the_page_shows() -> None:
    [sent] = _ask(Subject(kind="page", key="league"), "Who is running away with it?")

    assert "Shawoozals" in sent and "6-1" in sent


# ── the assistant ───────────────────────────────────────────────────────

WEEK = Subject(kind="page", key="week")
TEAM = Subject(kind="page", key="team")
WIRE = Subject(kind="page", key="free-agents")
GIBBS_ROW = "Jahmyr Gibbs"


def _assist(*turns: tuple[str, list[Subject]], answers: FakeAnswers | None = None) -> list[str]:
    """What the assistant sent the model for each (question, on screen) turn."""
    ai = FakeAI()
    assistant = AskEngine(OneWeek(), ai=ai, answers=answers or FakeAnswers()).assistant("L1")
    for question, on_screen in turns:
        assistant.ask(question, on_screen)
    return ai.chat.sent


def test_the_assistants_first_question_carries_the_page_on_screen() -> None:
    [sent] = _assist(("What should I do?", [WEEK]))

    assert TASK.title in sent
    assert sent.endswith("What should I do?")


def test_a_page_already_briefed_is_not_briefed_again() -> None:
    """Every turn resends the history; the page is in it once already."""
    _, second = _assist(("What should I do?", [WEEK]), ("And after that?", [WEEK]))

    assert TASK.title not in second


def test_a_page_opened_later_is_briefed_when_it_comes_on_screen() -> None:
    _, second = _assist(("What should I do?", [WEEK]), ("Who is worth adding?", [WIRE]))

    assert "Jonah Coleman" in second and "412" in second


def test_a_player_opened_over_a_page_is_briefed_beside_it() -> None:
    [sent] = _assist(("Is he the lead back?", [TEAM, Subject(kind="player", key="hall")]))

    assert GIBBS_ROW in sent and HALL.name in sent and "57%" in sent


def test_every_question_names_what_is_on_screen_even_once_briefed() -> None:
    """Otherwise "him" in the third question is whoever was briefed last."""
    hall = Subject(kind="player", key="hall")
    *_, third = _assist(("Is he good?", [hall]), ("And the week?", [WEEK]), ("Him again?", [hall]))

    assert HALL.name in third
    assert "57%" not in third


def test_a_question_asked_with_nothing_of_the_league_on_screen_is_still_answered() -> None:
    [sent] = _assist(("Which league am I in?", []))

    assert sent.endswith("Which league am I in?")


def test_an_item_gone_from_the_week_is_said_to_be_gone_to_the_assistant_too() -> None:
    with pytest.raises(SubjectGoneError):
        _assist(("Why?", [Subject(kind="task", key="swap:someone:else")]))


def test_the_roster_page_carries_what_each_row_rests_on_beside_the_table() -> None:
    [sent] = _assist(("Who is my weakest starter?", [TEAM]))

    assert GIBBS_ROW in sent and "Breece Hall (RB, NYJ)" in sent


def test_the_week_carries_the_moves_the_last_judgment_added_to_it() -> None:
    """They are rows on the page, so a briefing without them says there is nothing to do."""
    answers = FakeAnswers()
    answers.save(
        scout_scope(OneWeek.label, "L1"),
        Remembered(answer=MOCK_FPL_REPORT, answered_at=datetime.now(UTC), inputs="x"),
    )

    [sent] = _assist(("What is on my list?", [WEEK]), answers=answers)

    assert all(move.player in sent for move in MOCK_FPL_REPORT.moves)
