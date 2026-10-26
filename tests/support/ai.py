"""Stand-ins for the model: a conversation, and the `AnalysisModel` port."""

from types import SimpleNamespace
from typing import Any

from support.reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT


class FakeChat:
    """Stands in for an open conversation: answers with `reply`, or raises `error`."""

    def __init__(self, reply: str = "[FAKE] follow-up answer", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.sent: list[str] = []

    def send_message(self, message: Any) -> Any:
        self.sent.append(str(message))
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.reply)


class FakeAI:
    """Stands in for GeminiClient, recording what it was asked."""

    def __init__(
        self,
        report: Any = MOCK_NBA_REPORT,
        verdict: Any = MOCK_NBA_VERDICT,
        proposal: Any = None,
        prose: str = "[FAKE] trade prose",
        chat: FakeChat | None = None,
    ) -> None:
        self.report = report
        self.verdict = verdict
        self.proposal = proposal
        self.prose = prose
        self.prompts: list[str] = []
        self.structured_text: list[str] = []
        self.history: Any = None
        self.search_enabled: bool | None = None
        self.chat = chat or FakeChat()

    def generate_structured(self, prompt: str, schema: type, mock: Any = None) -> Any:
        """The scripted report, in whatever format was asked for: a model answers in the schema it is held to."""
        self.prompts.append(prompt)
        return self.report if isinstance(self.report, schema) else schema.model_validate(self.report.model_dump())

    def structure_text(self, text: str, schema: type, instruction: str, mock: Any = None) -> Any:
        self.structured_text.append(text)
        return self.verdict

    def start_chat(self, initial_history: Any = None, enable_search: bool = False) -> FakeChat:
        self.history = initial_history
        self.search_enabled = enable_search
        return self.chat

    def parse_trade_string(self, text: str) -> Any:
        from thefrontoffice.domain.models import TradeProposal

        return (
            self.proposal
            if self.proposal is not None
            else TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
        )
