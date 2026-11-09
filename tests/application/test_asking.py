"""Tests for questions asked of what is on screen: `application/asking.py`.

The provider is a stand-in with one to-do item, one player, a table and a
free-agent pool; the model is the conftest fake, whose chat records what was sent.
"""

from datetime import UTC, datetime

import pytest
from support.ai import FakeAI, FakeChat
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
    ScoutReport,
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

WEEK = Subject(kind="page", key="week")
TEAM = Subject(kind="page", key="team")
WIRE = Subject(kind="page", key="free-agents")
LEAGUE = Subject(kind="page", key="league")
ITEM = Subject(kind="task", key=TASK.key)
PLAYER = Subject(kind="player", key="hall")


class OneWeek:
    def __init__(self, movable: frozenset[str] | None = None) -> None:
        self.movable = movable

    def build_context(self, league_id: str) -> CompetitionContext:
        return CompetitionContext(
            prompt="prompt",
            situation="SITUATION: 3-3, chasing.",
            roster_lines={"Breece Hall": "- Breece Hall (RB, NYJ) vs MIA: 14.1 proj pts\n"},
            tasks=[TASK],
            movable=self.movable,
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


def _judged(report: ScoutReport = MOCK_FPL_REPORT) -> FakeAnswers:
    answers = FakeAnswers()
    answers.save(scout_scope("nfl-sleeper", "L1"), Remembered(answer=report, answered_at=datetime.now(UTC), inputs="x"))
    return answers


def _assist(
    *turns: tuple[str, list[Subject]],
    answers: FakeAnswers | None = None,
    week: OneWeek | None = None,
    chat: FakeChat | None = None,
) -> list[str]:
    """What the assistant sent the model for each (question, on screen) turn."""
    ai = FakeAI(chat=chat)
    assistant = AskEngine(week or OneWeek(), key="nfl-sleeper", ai=ai, answers=answers or FakeAnswers()).assistant("L1")
    for question, on_screen in turns:
        assistant.ask(question, on_screen)
    return ai.chat.sent


# ── what each subject is briefed with ───────────────────────────────────


def test_an_item_is_briefed_with_its_evidence_and_the_roster() -> None:
    [sent] = _assist(("Why?", [ITEM]))

    assert TASK.title in sent and TASK.when in sent
    assert all(line.value in sent for line in TASK.evidence)
    assert "Breece Hall (RB, NYJ)" in sent
    assert sent.endswith("Why?")


def test_an_earlier_verdict_on_the_item_is_part_of_its_briefing() -> None:
    judged = TASK.model_copy(
        update={"verdict": TaskVerdict(task="T1", decision="WAIT", reason="His status is due Sunday.")}
    )

    [sent] = _assist(("Why wait?", [ITEM]), answers=_judged(MOCK_FPL_REPORT.model_copy(update={"tasks": [judged]})))

    assert "His status is due Sunday." in sent


def test_an_item_the_week_no_longer_holds_is_said_to_be_gone() -> None:
    with pytest.raises(SubjectGoneError):
        _assist(("Why?", [Subject(kind="task", key="swap:someone:else")]))


def test_a_player_is_briefed_with_what_the_drawer_shows_and_the_roster() -> None:
    [sent] = _assist(("Is he the lead back?", [PLAYER]))

    assert HALL.name in sent and "57%" in sent and "Jahmyr Gibbs" in sent


def test_the_league_page_is_briefed_with_the_table() -> None:
    [sent] = _assist(("Who is running away with it?", [LEAGUE]))

    assert "Shawoozals" in sent and "6-1" in sent
    assert "abhibeast (you)" in sent


def test_the_free_agent_page_is_briefed_with_the_top_of_the_pool_and_its_size() -> None:
    [sent] = _assist(("Who is worth adding?", [WIRE]))

    assert "Jonah Coleman" in sent and "412" in sent


def test_the_roster_page_carries_what_each_row_rests_on_beside_the_table() -> None:
    [sent] = _assist(("Who is my weakest starter?", [TEAM]))

    assert "Jahmyr Gibbs" in sent and "Breece Hall (RB, NYJ)" in sent


def test_the_week_carries_the_moves_the_last_judgment_added_to_it() -> None:
    """They are rows on the page, so a briefing without them says there is nothing to do."""
    [sent] = _assist(("What is on my list?", [WEEK]), answers=_judged())

    assert TASK.title in sent
    assert all(move.player in sent for move in MOCK_FPL_REPORT.moves)


def test_the_week_leaves_out_a_kept_move_that_no_longer_stands() -> None:
    """The page drops a move whose player can no longer be moved, so the briefing does too."""
    [gone, *kept] = MOCK_FPL_REPORT.moves
    movable = frozenset(n for m in kept for n in (m.player, m.replaces) if n)

    [sent] = _assist(("What is on my list?", [WEEK]), answers=_judged(), week=OneWeek(movable=movable))

    assert gone.rationale not in sent
    assert all(move.rationale in sent for move in kept)


# ── the conversation ────────────────────────────────────────────────────


def test_a_page_already_briefed_is_not_briefed_again() -> None:
    """Every turn resends the history; the page is in it once already."""
    first, second = _assist(("What should I do?", [WEEK]), ("And after that?", [WEEK]))

    assert TASK.reason in first
    assert TASK.reason not in second


def test_a_page_opened_later_is_briefed_when_it_comes_on_screen() -> None:
    _, second = _assist(("What should I do?", [WEEK]), ("Who is worth adding?", [WIRE]))

    assert "Jonah Coleman" in second


def test_a_player_opened_over_a_page_is_briefed_beside_it() -> None:
    [sent] = _assist(("Is he the lead back?", [TEAM, PLAYER]))

    assert "Jahmyr Gibbs" in sent and HALL.name in sent and "57%" in sent


def test_every_question_names_what_is_on_screen_even_once_briefed() -> None:
    """Otherwise "him" in the third question is whoever was briefed last."""
    *_, third = _assist(("Is he good?", [PLAYER]), ("And the week?", [WEEK]), ("Him again?", [PLAYER]))

    assert HALL.name in third
    assert "57%" not in third


def test_a_question_asked_with_nothing_of_the_league_on_screen_is_still_answered() -> None:
    [sent] = _assist(("Which league am I in?", []))

    assert sent.endswith("Which league am I in?")


def test_a_question_the_model_never_answered_leaves_what_rode_with_it_unbriefed() -> None:
    """A failed question was never taken into the conversation, so neither was its briefing."""
    chat = FakeChat(error=RuntimeError("quota"))
    ai = FakeAI(chat=chat)
    assistant = AskEngine(OneWeek(), key="nfl-sleeper", ai=ai, answers=FakeAnswers()).assistant("L1")
    with pytest.raises(RuntimeError):
        assistant.ask("Is he good?", [PLAYER])
    chat.error = None

    assistant.ask("Is he good?", [PLAYER])

    assert "57%" in chat.sent[-1]
