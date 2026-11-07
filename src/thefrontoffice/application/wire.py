"""Calls on the free agents a manager is looking at.

The list is the platform's and the ranking is computed; the model is asked
only about the rows on screen, and its answer is kept only where it is about
one of them — once.

Each call is kept per player, against that player's own lines in the prompt:
his projection, role, matchup, news and fit. So judging a page again asks
only about the players whose situation has moved, and showing the page
again shows every kept call without asking — the moved ones marked stale.
"""

import logging

from thefrontoffice.application.answers import Answers, is_current, scope
from thefrontoffice.application.formats import WireAnswer
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import MAX_PAGE, CompetitionContext, PlayerCall
from thefrontoffice.domain.ports import AnalysisModel, AnswerStore, WireProvider

logger = logging.getLogger(__name__)

MAX_JUDGED = 10
"""Enough to cover a screen's worth of the best candidates; few enough that
every one gets a considered line rather than a sentence fragment."""

MAX_SHOWN = MAX_PAGE
"""As many kept calls as a page of the wire can show at once."""


class WireEngine:
    """Turns any WireProvider into calls on the players asked about."""

    def __init__(self, provider: WireProvider, *, key: str, ai: AnalysisModel, answers: AnswerStore):
        """Every collaborator is a port, wired by `bootstrap.Wiring`; `key` names the competition."""
        self.provider = provider
        self.key = key
        self.ai = ai
        self.answers = Answers(answers)

    def judge(self, league_id: str, player_ids: list[str]) -> list[PlayerCall]:
        """A current call on each player asked about, asking the model only where needed.

        A player no longer available is skipped rather than failing the rest.

        Raises:
            AIUnavailableError, AIResponseError, AIQuotaError: as the model reports.
        """
        return self._calls(league_id, _distinct(player_ids)[:MAX_JUDGED], ask=True)

    def kept(self, league_id: str, player_ids: list[str]) -> list[PlayerCall]:
        """The kept call on each player asked about, without asking anything — stale ones marked.

        A player no longer available is skipped rather than failing the rest.
        """
        return self._calls(league_id, _distinct(player_ids)[:MAX_SHOWN], ask=False)

    def _calls(self, league_id: str, asked: list[str], ask: bool) -> list[PlayerCall]:
        try:
            context = self.provider.build_wire_context(league_id, asked)
        except PlayerNotFoundError as e:
            # Claimed between the page loading and this request: no longer a
            # free agent, so no call to show or make — but no reason to lose
            # every other row's over him.
            asked = [pid for pid in asked if pid not in e.names]
            logger.info(f"{self.key}: {', '.join(e.names)} no longer available; skipping")
            if not asked:
                return []
            context = self.provider.build_wire_context(league_id, asked)
        calls: dict[str, PlayerCall] = {}
        due: list[str] = []
        for player_id in asked:
            kept = self.answers.latest(self._scope(league_id, player_id), PlayerCall)
            line = context.targets.get(player_id, "")
            current = kept is not None and is_current(kept, line)
            if kept is not None and (current or not ask):
                calls[player_id] = kept.answer.model_copy(update={"judged_at": kept.answered_at, "stale": not current})
            elif ask:
                due.append(player_id)

        if due:
            # The prompt holds only the players being asked about: the model
            # should not be shown players whose calls stand. Where none stand,
            # the context already built is that prompt.
            asking = context if due == asked else self.provider.build_wire_context(league_id, due)
            calls.update(self._ask(league_id, due, asking))
        return [calls[pid] for pid in asked if pid in calls]

    def _ask(self, league_id: str, due: list[str], context: CompetitionContext) -> dict[str, PlayerCall]:
        """Calls on `due` from the model, each kept against the lines it was given in `context`.

        Checked later against the lines a context for a different set of
        players holds — which `WireProvider` promises are the same.
        """
        answer = self.ai.generate_structured(context.prompt, WireAnswer)

        # Only the players asked about, and each once: a call on someone not
        # on screen has no row to sit on, and a second call on the same row
        # contradicts the first.
        answered: dict[str, PlayerCall] = {}
        for call in answer.calls:
            if call.player_id in due and call.player_id not in answered:
                clean = PlayerCall.model_validate(call.model_dump())
                kept = self.answers.keep(
                    self._scope(league_id, call.player_id), context.targets.get(call.player_id, ""), clean
                )
                answered[call.player_id] = clean.model_copy(update={"judged_at": kept.answered_at})
            else:
                logger.warning(f"{self.key}: dropping a call on {call.player_id!r}, unasked or repeated")
        return answered

    def _scope(self, league_id: str, player_id: str) -> str:
        return scope("wire", self.key, league_id, player_id)


def _distinct(player_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(player_ids))
