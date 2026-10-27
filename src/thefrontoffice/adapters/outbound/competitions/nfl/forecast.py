"""This week's matchup as the simulation reads it: each starter's range, and the moves worth pricing.

The generic engine in `application/forecasting.py` plays it out; this says
what football's week is made of — whose game is under way and how far, who
is questionable, which bench and waiver starts are legal. Also the same for a
week already played, which is what the simulation is scored and tuned on.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from typing import Any

from thefrontoffice.adapters.outbound.competitions.nfl import evidence, outcomes
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import fits
from thefrontoffice.adapters.outbound.competitions.nfl.model import LeagueRules, NFLSource, Projection, Team
from thefrontoffice.adapters.outbound.competitions.nfl.rules import SEASON_WEEKS, ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.week import Scoreboard, Week, left_in, projection_for
from thefrontoffice.domain.errors import PlatformError
from thefrontoffice.domain.models import Action, LineupMove, MatchupInput, Outcomes, PlayedMatchup

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
                lines = self.client.get_nfl_game_lines(str(int(season) - 1), list(range(1, SEASON_WEEKS + 1)))
            except (PlatformError, ValueError) as e:
                logger.warning(f"Shaping ranges without last season: {e}")
                lines = []
            self._previous[key] = evidence.gather(lines, scoring)
        return self._previous[key]

    def matchup(
        self,
        state: Week,
        league_id: str,
        scoreboard: Scoreboard,
        opponent: Team,
        to_do: list[Action],
        candidates: Sequence[str],
        owned: set[str],
        seeded: int,
    ) -> MatchupInput:
        """This week's matchup: both lineups, and the moves worth pricing.

        The moves are every single swap your bench allows — the simulation
        finds the one a projection would not — and every waiver pickup the
        to-do list names. With `candidates` they are instead every legal
        start of each of those free agents, priced as if already claimed.
        """
        games = scoreboard.games(state)
        status = {club: game.status for game in games.get(state.week, []) for club in (game.home, game.away)}
        board = scoreboard.board(state)
        live = scoreboard.live(state, league_id)
        spread = outcomes.spreads(state.evidence, pool_from=self.last_season(state.season, state.league.scoring_format))

        def outcome(player: Projection) -> Outcomes:
            return outcomes.outcomes(
                player,
                spread,
                status=status.get(player.team, ""),
                scored=live.points.get(player.player_id, 0.0),
                left=left_in(board[player.team]) if player.team in board else outcomes.UNDER_WAY,
            )

        started = {club for club, s in status.items() if s and s != "pre_game"}
        # The wire is priced against the lineup your bench would already make:
        # against the one as set, a free agent is credited with filling a slot
        # a bench player fills anyway.
        lineup = settled(state, started) if candidates else [slot.player for slot in state.lineup if slot.player]
        mine = tuple(outcome(p) for p in lineup)
        theirs = tuple(
            outcome(p)
            for p in (
                projection_for(pid, state.projections, state.players) for pid in opponent.starter_ids if pid != "0"
            )
            if p
        )
        if candidates:
            wire = [state.projections[pid] for pid in candidates if pid in state.projections and pid not in owned]
            moves = starts(state, lineup, wire, outcome, started)
        else:
            bench = [p for p in state.projected if p.player_id not in state.starter_ids]
            moves = starts(state, lineup, bench, outcome, started) + pickups(state, to_do, outcome)
        return MatchupInput(mine=mine, theirs=theirs, moves=moves, seed=seeded)

    def played_week(
        self, league: LeagueRules, week: int
    ) -> tuple[evidence.Evidence, evidence.Evidence, list[tuple[Projection, float]]]:
        """A finished week's players, for scoring ranges: what was known before it, and what each scored.

        Every player who took the field and was projected at least a few
        points — the ones a range is ever drawn for — paired with his actual
        score. What was known is the games before it alone, so nothing a
        range is scored against shaped it.
        """
        season = self.client.get_nfl_state().season
        lines = self.client.get_nfl_game_lines(season, list(range(1, week + 1)))
        before = evidence.gather([line for line in lines if line.week < week], league.scoring_format)
        last = self.last_season(season, league.scoring_format)
        projections = self.client.get_projections(season, week, league.scoring_format)
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
        season = self.client.get_nfl_state().season
        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        earlier = list(range(1, week))
        lines = self.client.get_nfl_game_lines(season, earlier) if earlier else []
        spread = outcomes.spreads(
            evidence.gather(lines, league.scoring_format),
            settings,
            pool_from=self.last_season(season, league.scoring_format),
        )

        def side(entry: dict[str, Any]) -> tuple[Outcomes, ...]:
            starters = [str(pid) for pid in entry.get("starters") or [] if str(pid) not in ("0", "")]
            return tuple(
                outcomes.outcomes(p, spread, settings=settings)
                for p in (projection_for(pid, projections, players) for pid in starters)
                if p
            )

        paired: dict[Any, list[dict[str, Any]]] = {}
        for entry in self.client.get_matchups(league.league_id, week):
            if entry.get("matchup_id") is not None:
                paired.setdefault(entry["matchup_id"], []).append(entry)

        played = []
        for matchup_id, entries in paired.items():
            if len(entries) != 2:
                continue
            first, second = sorted(entries, key=lambda e: int(e.get("roster_id") or 0))
            played.append(
                PlayedMatchup(
                    week=week,
                    matchup=MatchupInput(mine=side(first), theirs=side(second), seed=seeded(matchup_id)),
                    mine=float(first.get("points") or 0),
                    theirs=float(second.get("points") or 0),
                )
            )
        return played


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


STARTS = ("hole:", "upgrade:")
"""The to-do items whose pickup goes straight into the lineup."""


def pickups(state: Week, to_do: list[Action], outcome: Callable[[Projection], Outcomes]) -> tuple[LineupMove, ...]:
    """The pickups that start this week — filling a hole, or replacing a starter they outscore — priced as if claimed.

    Only those: a bye warning names your own starter, and a breakout is a
    stash for the bench — priced as a start, either would be a player
    added to a full lineup, which no move can do.
    """
    moves = []
    for action in to_do:
        projection = state.projections.get(action.player_id)
        if action.kind != "waiver" or not action.key.startswith(STARTS) or projection is None:
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
