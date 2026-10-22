"""Calls on the free agents a manager is looking at.

The list is the platform's and the ranking is computed; the model is asked
only about the rows on screen, and its answer is kept only where it is about
one of them — once.
"""

import logging

from thefrontoffice.domain.models import PlayerCall, WireReport
from thefrontoffice.domain.ports import AnalysisModel, WireProvider

logger = logging.getLogger(__name__)

MAX_JUDGED = 10
"""Enough to cover a screen's worth of the best candidates; few enough that
every one gets a considered line rather than a sentence fragment."""


class WireEngine:
    """Turns any WireProvider into calls on the players asked about."""

    def __init__(self, provider: WireProvider, *, ai: AnalysisModel):
        """Both collaborators are ports, wired by `bootstrap.wire_engine`."""
        self.provider = provider
        self.ai = ai

    def judge(self, league_id: str, player_ids: list[str]) -> list[PlayerCall]:
        """One call per player asked about, in the order asked, for those the model answered.

        Raises:
            PlayerNotFoundError: an id is not an available player.
            AIUnavailableError, AIResponseError, AIQuotaError: as the model reports.
        """
        asked = list(dict.fromkeys(player_ids))[:MAX_JUDGED]
        context = self.provider.build_wire_context(league_id, asked)
        report = self.ai.generate_structured(context.prompt, WireReport)

        # Only the players asked about, and each once: a call on someone not
        # on screen has no row to sit on, and a second call on the same row
        # contradicts the first.
        by_player: dict[str, PlayerCall] = {}
        for call in report.calls:
            if call.player_id in asked and call.player_id not in by_player:
                by_player[call.player_id] = call
            else:
                logger.warning(f"{self.provider.label}: dropping a call on {call.player_id!r}, unasked or repeated")
        return [by_player[pid] for pid in asked if pid in by_player]
