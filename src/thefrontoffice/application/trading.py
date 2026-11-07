"""The generic trade pipeline.

Identical for every competition: parse the proposal, ask the provider to price both
sides, and return a validated verdict. Which competitions can do this is declared by
the registry, not tested here.
"""

import logging

from thefrontoffice.application.formats import TradeAnswer, TradeSides
from thefrontoffice.domain.errors import TradeParseError
from thefrontoffice.domain.models import TradeProposal, TradeVerdict
from thefrontoffice.domain.ports import AnalysisModel, ChatSession, TradeProvider

logger = logging.getLogger(__name__)

SIDES_INSTRUCTION = "Extract the players being given and received in this trade offer, using full player names."

VERBATIM = "Convert the following analysis verbatim — do not add, drop or soften anything."
"""What structuring prose the model already wrote must not do: a second pass that
rephrased the verdict would be a second, unsearched opinion."""

EVALUATION_INSTRUCTION = f"Extract this fantasy trade evaluation into the given structure. {VERBATIM}"


class TradeEngine:
    """Turns any TradeProvider into a trade verdict."""

    def __init__(self, provider: TradeProvider, *, ai: AnalysisModel):
        """Both collaborators are ports, which `Wiring.trade` in the composition root fills."""
        self.provider = provider
        self.ai = ai

    def evaluate(self, league_id: str, trade_text: str) -> tuple[TradeVerdict, ChatSession]:
        """Evaluate a trade described in plain language.

        Raises:
            TradeParseError: the description could not be split into two sides.
            PlayerNotFoundError: a named player could not be resolved.
            AIResponseError: the model failed or returned nothing usable.
        """
        sides = self.ai.structure_text(trade_text, TradeSides, instruction=SIDES_INSTRUCTION)
        proposal = TradeProposal(giving=sides.giving, receiving=sides.receiving)
        if not proposal.is_valid:
            raise TradeParseError(trade_text)
        logger.info(f"Parsed trade — giving {proposal.giving}, receiving {proposal.receiving}")

        context = self.provider.build_trade_context(league_id, proposal)

        # Search stays enabled where the model offers it: live injury and
        # standings news is most of the value in a trade call. A model may not
        # accept a response schema alongside a tool, so the search-grounded
        # prose is structured in a cheap second pass.
        chat = self.ai.start_chat(enable_search=True)
        text = chat.send_message(context.prompt).text
        answer = self.ai.structure_text(text, TradeAnswer, instruction=EVALUATION_INSTRUCTION)
        return TradeVerdict.model_validate(answer.model_dump()), chat
