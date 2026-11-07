"""Stand-ins for the model: a conversation, and the `AnalysisModel` port."""

from pydantic import BaseModel

from support.reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT
from thefrontoffice.application.formats import TradeSides
from thefrontoffice.domain.models import TradeProposal
from thefrontoffice.domain.ports import ChatReply, HistoryTurn, TModel


class FakeChat:
    """Stands in for an open conversation: answers with `reply`, or raises `error`."""

    def __init__(self, reply: str = "[FAKE] follow-up answer", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.sent: list[str] = []

    def send_message(self, message: str) -> ChatReply:
        self.sent.append(message)
        if self.error:
            raise self.error
        return ChatReply(text=self.reply)


class FakeAI:
    """Stands in for the model, recording what it was asked.

    Answers in whatever format it is held to, as a model does: `report` for an
    analysis, `proposal` for a trade's two sides, `verdict` for anything else
    it structures.
    """

    def __init__(
        self,
        report: BaseModel = MOCK_NBA_REPORT,
        verdict: BaseModel = MOCK_NBA_VERDICT,
        proposal: TradeProposal | None = None,
        chat: FakeChat | None = None,
        available: bool = True,
    ) -> None:
        self.report = report
        self.verdict = verdict
        self.proposal = proposal or TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
        self.available = available
        self.prompts: list[str] = []
        self.structured: list[tuple[str, type[BaseModel], str]] = []
        self.history: list[HistoryTurn] = []
        """What the last chat opened was seeded with."""
        self.search_enabled: bool | None = None
        self.chat = chat or FakeChat()

    @property
    def is_available(self) -> bool:
        return self.available

    def generate_structured(self, prompt: str, schema: type[TModel]) -> TModel:
        self.prompts.append(prompt)
        return schema.model_validate(self.report.model_dump())

    def structure_text(self, text: str, schema: type[TModel], instruction: str) -> TModel:
        self.structured.append((text, schema, instruction))
        if schema is TradeSides:
            return schema.model_validate({"giving": self.proposal.giving, "receiving": self.proposal.receiving})
        return schema.model_validate(self.verdict.model_dump())

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> FakeChat:
        self.history = list(initial_history or [])
        self.search_enabled = enable_search
        return self.chat
