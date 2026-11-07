"""This week's matchup as the simulation reads it: each starter's range, and the moves worth pricing.

The generic engine in `application/forecasting.py` plays it out; this says
what football's week is made of — whose game is under way and how far, who
is questionable, which bench and waiver starts are legal. Also the same for a
week already played, which is what the simulation is scored and tuned on.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence

from thefrontoffice.adapters.outbound.competitions.nfl import evidence, outcomes
from thefrontoffice.adapters.outbound.competitions.nfl.actions import Item
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import fits
from thefrontoffice.adapters.outbound.competitions.nfl.model import LeagueRules, Matchup, NFLSource, Projection, Team
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS, SEASON_WEEKS, ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Scoreboard,
    Week,
    left_in,
    pairings,
    projections_for,
)
from thefrontoffice.domain.errors import PlatformError
from thefrontoffice.domain.models import LineupMove, MatchupInput, Outcomes, PlayedMatchup

logger = logging.getLogger(__name__)

SCORED_FROM = 3.0
"""Projected points below which a player is nobody's start, and his range not worth scoring."""


def seed(*parts: object) -> int:
    """The same simulation for the same week, so the numbers hold still between reloads."""
    return int(hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).hexdigest()[:12], 16)


class Forecasts:
    """Matchups ready to simulate, for this week and for weeks already played.

    Holds last season's games once read: they shape every position's spread,
    are the same all season, and are the largest fetch in a forecast.
    """

    def __init__(self, client: NFLSource):
        self.client = client
        self._previous: dict[str, evidence.Evidence] = {}

    def last_season(self, season: str, scoring: str) -> evidence.Evidence:
        """Last season's games, for the shape of each position's spread. Empty where they will not load."""
        key = f"{season}:{scoring}"
        if key not in self._previous:
            try:
                lines = self.client.get_nfl_game_lines(
                    str(int(season) - 1), list(range(1, SEASON_WEEKS + 1)), FANTASY_POSITIONS
                )
            except (PlatformError, ValueError) as e:
                logger.warning(f"Shaping ranges without last season: {e}")
                lines = []
            self._previous[key] = evidence.gather(lines, scoring)
        return self._previous[key]

    def matchup(
        self, state: Week, scoreboard: Scoreboard, opponent: Team, to_do: Sequence[Item], seeded: int
    ) -> MatchupInput:
        """This week's matchup: both lineups, and the moves worth pricing.

        The moves are every single swap your bench allows — the simulation
        finds the one a projection would not — and every waiver pickup the
        to-do list names.
        """
        outcome = self._outcomes(state, scoreboard)
        started = scoreboard.started(state)
        lineup = [slot.player for slot in state.lineup if slot.player]
        moves = starts(state, lineup, state.bench, outcome, started) + pickups(state, to_do, outcome)
        return MatchupInput(
            mine=_side(lineup, outcome), theirs=_theirs(state, opponent, outcome), moves=moves, seed=seeded
        )

    def wire(
        self, state: Week, scoreboard: Scoreboard, opponent: Team, candidates: Sequence[str], seeded: int
    ) -> MatchupInput:
        """This week's matchup with every legal start of each of these free agents, priced as if already claimed.

        Priced against the lineup your bench would already make: against the
        one as set, a free agent is credited with filling a slot a bench
        player fills anyway.
        """
        outcome = self._outcomes(state, scoreboard)
        started = scoreboard.started(state)
        lineup = settled(state, started)
        wire = [state.projections[pid] for pid in candidates if pid in state.projections and pid not in state.owned]
        moves = starts(state, lineup, wire, outcome, started)
        return MatchupInput(
            mine=_side(lineup, outcome), theirs=_theirs(state, opponent, outcome), moves=moves, seed=seeded
        )

    def _outcomes(self, state: Week, scoreboard: Scoreboard) -> Callable[[Projection], Outcomes]:
        """Each player's week as a range: shaped by his games, and by how far into it his own game is."""
        status = {
            club: game.status for game in scoreboard.games(state).get(state.week, []) for club in (game.home, game.away)
        }
        board = scoreboard.board(state)
        live = scoreboard.live(state)
        spread = outcomes.spreads(state.evidence, pool_from=self.last_season(state.season, state.league.scoring_format))

        def outcome(player: Projection) -> Outcomes:
            return outcomes.outcomes(
                player,
                spread,
                status=status.get(player.team, ""),
                scored=live.scored(player.player_id, player.team) or 0.0,
                left=left_in(board[player.team]) if player.team in board else outcomes.UNDER_WAY,
            )

        return outcome

    def played_week(
        self, league: LeagueRules, week: int
    ) -> tuple[evidence.Evidence, evidence.Evidence, list[tuple[Projection, float]]]:
        """A finished week's players, for scoring ranges: what was known before it, and what each scored.

        Every player who took the field and was projected at least a few
        points — the ones a range is ever drawn for — paired with his actual
        score. What was known is the games before it alone, so nothing a
        range is scored against shaped it.
        """
        season = league.season
        lines = self.client.get_nfl_game_lines(season, list(range(1, week + 1)), FANTASY_POSITIONS)
        before = evidence.gather([line for line in lines if line.week < week], league.scoring_format)
        last = self.last_season(season, league.scoring_format)
        projections = self.client.get_projections(season, week, league.scoring_format, FANTASY_POSITIONS)
        that_week = evidence.gather([line for line in lines if line.week == week], league.scoring_format)
        played = [
            (projections[pid], games[0])
            for pid, games in that_week.games.items()
            if pid in projections and projections[pid].points >= SCORED_FROM
        ]
        return before, last, played

    def played_matchups(
        self, league: LeagueRules, week: int, settings: outcomes.RangeSettings, seeded: Callable[[object], int]
    ) -> list[PlayedMatchup]:
        """Every matchup of `week`, rebuilt as it stood before kickoff, with how it ended.

        As it stood: that week's projections and starters, and only the games
        played before it — a range shaped by the week being predicted would
        be the answer leaking into the question.
        """
        season = league.season
        projections = self.client.get_projections(season, week, league.scoring_format, FANTASY_POSITIONS)
        players = self.client.get_nfl_players()
        earlier = list(range(1, week))
        lines = self.client.get_nfl_game_lines(season, earlier, FANTASY_POSITIONS) if earlier else []
        spread = outcomes.spreads(
            evidence.gather(lines, league.scoring_format),
            settings,
            pool_from=self.last_season(season, league.scoring_format),
        )

        def side(entry: Matchup) -> tuple[Outcomes, ...]:
            return tuple(
                outcomes.outcomes(p, spread, settings=settings)
                for p in projections_for(entry.starters, projections, players)
            )

        return [
            PlayedMatchup(
                week=week,
                matchup=MatchupInput(mine=side(first), theirs=side(second), seed=seeded(first.matchup_id)),
                mine=first.points,
                theirs=second.points,
            )
            for first, second in pairings(self.client.get_matchups(league.league_id, week))
        ]


def _side(players: Sequence[Projection], outcome: Callable[[Projection], Outcomes]) -> tuple[Outcomes, ...]:
    return tuple(outcome(p) for p in players)


def _theirs(state: Week, opponent: Team, outcome: Callable[[Projection], Outcomes]) -> tuple[Outcomes, ...]:
    """Who they start, as their lineup is set: an empty slot scores nothing and has no range."""
    return _side(projections_for(opponent.starter_ids, state.projections, state.players), outcome)


def settled(state: Week, started: set[str]) -> list[Projection]:
    """Your starters once the bench has made every swap it still can: the lineup a pickup has to beat."""
    starters = [slot.player for slot in state.lineup if slot.player]
    for change in state.changes:
        if change.start.team in started or (change.bench is not None and change.bench.team in started):
            continue
        out = change.bench.player_id if change.bench else None
        starters = [p for p in starters if p.player_id != out] + [change.start]
    return starters


def starts(
    state: Week,
    starters: Sequence[Projection],
    players: Sequence[Projection],
    outcome: Callable[[Projection], Outcomes],
    started: set[str],
) -> tuple[LineupMove, ...]:
    """Every single start of one of `players` into `starters` that leaves a legal lineup, among players not yet locked.

    A lineup is a set of starters, so a swap is one in and one out — legal
    if the new set fills the slots any way at all. Hall for Bernard is one,
    though Hall cannot play Bernard's WR slot: the flex slides across.
    The same for a bench player and a free agent: who he is does not
    change which lineups he makes.
    """
    slots = state.league.starting_slots
    eligible = [p for p in players if p.team not in started and not ruled_out(p.injury_status) and p.opponent]
    moves = []
    for candidate in eligible:
        if len(starters) < len(slots) and fits(slots, [*starters, candidate]):
            moves.append(
                LineupMove(
                    key=f"{candidate.player_id}>",
                    title=f"Start {candidate.name} in your empty slot",
                    out=(),
                    into=(outcome(candidate),),
                )
            )
        for out in starters:
            if out.team in started:
                continue
            lineup = [p for p in starters if p.player_id != out.player_id] + [candidate]
            if fits(slots, lineup):
                moves.append(
                    LineupMove(
                        key=f"{candidate.player_id}>{out.player_id}",
                        title=f"Start {candidate.name} over {out.name}",
                        out=(out.player_id,),
                        into=(outcome(candidate),),
                    )
                )
    return tuple(moves)


def pickups(state: Week, to_do: Sequence[Item], outcome: Callable[[Projection], Outcomes]) -> tuple[LineupMove, ...]:
    """The pickups that start this week — filling a hole, or replacing a starter they outscore — priced as if claimed.

    Only those: a bye warning names your own starter, and a breakout is a
    stash for the bench — priced as a start, either would be a player
    added to a full lineup, which no move can do.
    """
    moves = []
    for item in to_do:
        action = item.action
        projection = state.projections.get(action.player_id)
        if not item.starts_now or projection is None:
            continue
        moves.append(
            LineupMove(
                key=f"{action.player_id}>{action.replaces}",
                title=action.title,
                out=(action.replaces,) if action.replaces else (),
                into=(outcome(projection),),
            )
        )
    return tuple(moves)
