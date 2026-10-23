"""The generic trade pipeline.

Identical for every competition: parse the proposal, ask the provider to price both
sides, and return a validated verdict. Which competitions can do this is declared by
the registry, not tested here.
"""

import logging

from thefrontoffice.domain.errors import AIResponseError, FrontOfficeError, TradeParseError
from thefrontoffice.domain.models import TradeVerdict
from thefrontoffice.domain.ports import AnalysisModel, ChatSession, TradeProvider

logger = logging.getLogger(__name__)

STRUCTURE_INSTRUCTION = "Extract this fantasy trade evaluation into the given structure."


class TradeEngine:
    """Turns any TradeProvider into a trade verdict."""

    def __init__(self, provider: TradeProvider, *, ai: AnalysisModel):
        """Both collaborators are ports. `bootstrap.trade_engine` wires them."""
        self.provider = provider
        self.ai = ai

    def evaluate(self, league_id: str, trade_text: str) -> tuple[TradeVerdict, ChatSession]:
        """Evaluate a trade described in plain language.

        Raises:
            TradeParseError: the description could not be split into two sides.
            PlayerNotFoundError: a named player could not be resolved.
            AIResponseError: the model failed or returned nothing usable.
        """
        proposal = self.ai.parse_trade_string(trade_text)
        if not proposal.is_valid:
            raise TradeParseError(trade_text)
        logger.info(f"Parsed trade — giving {proposal.giving}, receiving {proposal.receiving}")

        context = self.provider.build_trade_context(league_id, proposal)

        # Google Search stays enabled: live injury and standings news is most of
        # the value in a trade call. The Gemini API will not accept a response
        # schema alongside a tool, so the search-grounded prose is structured in
        # a cheap second pass.
        chat = self.ai.start_chat(enable_search=True)
        try:
            response = chat.send_message(context.prompt)
        except FrontOfficeError:
            raise
        except Exception as e:
            # A vendor exception from the chat path, which has no translation of
            # its own; the message is a payload repr, so it stays in the log.
            logger.error(f"Error evaluating trade: {e}")
            raise AIResponseError() from e

        text = getattr(response, "text", None)
        if not text:
            raise AIResponseError("The model returned an empty trade evaluation.")

        verdict = self.ai.structure_text(text, TradeVerdict, instruction=STRUCTURE_INSTRUCTION)
        return verdict, chat
