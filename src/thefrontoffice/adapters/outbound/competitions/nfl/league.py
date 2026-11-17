"""The league beyond this week: the season, the table, the real games, the moves.

Separate from the week because it answers a different question asked at a
different time — how the season is going, rather than what to do about Sunday —
and it costs requests the week does not need. Nobody checking a lineup should
wait on eighteen weeks of matchups.
"""

import logging
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from thefrontoffice.adapters.outbound.competitions import places
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import SNAP_POSITIONS, misses, season_lines
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import lineup_points
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    LeagueMove,
    LeagueRules,
    Matchup,
    NFLSource,
    Projection,
    Team,
    active,
)
from thefrontoffice.adapters.outbound.competitions.nfl.outcomes import UNDER_WAY
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS, SEASON_WEEKS
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Scoreboard,
    Week,
    day,
    left_in,
    lineup_for,
    moment,
    opponent_of,
    pairings,
    projections_for,
    week_dates,
    weeks_played,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import ScoreboardGame
from thefrontoffice.domain.errors import PlatformError
from thefrontoffice.domain.models import (
    ActivityMove,
    ActivityRow,
    Fixture,
    LeagueSchedule,
    Match,
    Outcome,
    ScheduleRow,
    SeasonInput,
    StandingRow,
    Stat,
    TeamRecord,
    TeamWeek,
    outcome,
)

logger = logging.getLogger(__name__)


# "What did I miss", not the season's whole transaction log.
UNLOADED = "unavailable"
"""A week whose matchups would not load, in place of an opponent: not "bye", which it may not be."""

ACTIVITY_WEEKS = 3

TRANSACTION_LABELS = {
    "waiver": "Waiver",
    "free_agent": "Free agent",
    "trade": "Trade",
    "commissioner": "Commissioner",
}


def build(client: NFLSource, state: Week, schedule: Mapping[int, Sequence[Game]]) -> LeagueSchedule:
    """The season, the table, this week's real games, and what the league did."""
    standings = _standings(state)
    return LeagueSchedule(
        headline=_headline(state, standings),
        season=_season_rows(client, state, schedule),
        standings=standings,
        matches=matches(state, schedule.get(state.week, []), {}),
        activity=_activity(client, state),
    )


def _season_rows(client: NFLSource, state: Week, schedule: Mapping[int, Sequence[Game]]) -> list[ScheduleRow]:
    """Your own season, week by week, with who you play and how it went.

    Eighteen matchup fetches, run concurrently and cached — asked one at a
    time they are the whole wait on the page.
    """
    weeks = list(range(1, last_week(state) + 1))
    by_week = client.get_matchups_bulk(state.league.league_id, weeks)
    by_roster = {r.roster_id: r for r in state.rosters}

    rows: list[ScheduleRow] = []
    for week in weeks:
        loaded = week not in by_week.failures
        # The week being played is read from the matchups the week page reads, so the two
        # cannot show different scores for it: the bulk read is a separate fetch, cached apart.
        sides = (
            state.matchup if week == state.week else opponent_of(by_week.values.get(week, []), state.roster.roster_id)
        )
        opponent = by_roster.get(sides[1].roster_id) if sides else None

        playoff = _playoff_round(state, week)
        if playoff and week > state.week:
            # Sleeper fills the bracket weeks with placeholder pairings until
            # the regular season ends; a name there is not who you will play.
            opponent = None
        rows.append(
            ScheduleRow(
                label=f"Week {week}",
                date=week_dates(schedule.get(week, [])),
                opponent=state.names.get(opponent.owner_id, "") if opponent else "",
                detail=playoff or (opponent.record if opponent else "bye" if loaded else UNLOADED),
                result=_result(sides, week, state.week),
                marks=["Trade deadline"] if week == state.league.trade_deadline else [],
                outcome=_outcome(sides, week, state.week),
                is_current=week == state.week,
                playoffs=bool(playoff),
            )
        )
    return rows


def last_week(state: Week) -> int:
    """The league's final week: the end of its playoffs, or the NFL's last where it names none."""
    return season_end(state.league)


def season_end(rules: LeagueRules) -> int:
    """The final week of a league's season, before any week of it has been gathered."""
    start, teams = rules.playoff_week_start, rules.playoff_teams
    if not start or not teams:
        return SEASON_WEEKS
    return min(SEASON_WEEKS, start + math.ceil(math.log2(teams)) - 1)


def _playoff_round(state: Week, week: int) -> str:
    """'Playoffs, round 1' for a bracket week; empty for the regular season."""
    start = state.league.playoff_week_start
    return f"Playoffs, round {week - start + 1}" if start and week >= start else ""


def _headline(state: Week, standings: list[StandingRow]) -> list[Stat]:
    """Your season in figures: the record, where it puts you, and the points behind it."""
    rank = next((row.rank for row in standings if row.is_mine), 0)
    return [
        *places.season(state.roster.record, rank, len(standings)),
        Stat(label="Points for", value=f"{state.roster.points_for:.2f}"),
        *deadline(state),
    ]


def deadline(state: Week) -> list[Stat]:
    """The league's trade deadline against the week being played; none where the league set none.

    Warned once it is this week or next, because that is when a trade still
    has to be found, offered and accepted in time.
    """
    last = state.league.trade_deadline
    if not last:
        return []
    weeks = last - state.week
    if weeks < 0:
        return [Stat(label="Trade deadline", value=f"Week {last} · passed")]
    when = "this week" if weeks == 0 else "next week" if weeks == 1 else f"in {weeks} weeks"
    return [Stat(label="Trade deadline", value=f"Week {last} · {when}", tone="warning" if weeks <= 1 else "neutral")]


def _result(sides: tuple[Matchup, Matchup] | None, week: int, current: int) -> str:
    """The score, and only once there is one: final for a week played, so far for the week being played.

    A future week is not 0-0, and nor is the week being played before anybody has scored.
    """
    if week > current or sides is None:
        return ""
    mine, theirs = sides
    if week == current and not (mine.points or theirs.points):
        return ""
    return f"{mine.points:.2f}-{theirs.points:.2f}"


def _outcome(sides: tuple[Matchup, Matchup] | None, week: int, current: int) -> Outcome | None:
    """How a played week ended; None for one still to come, or a bye."""
    if week >= current or sides is None:
        return None
    mine, theirs = sides
    return outcome(mine.points, theirs.points)


def _standings(state: Week) -> list[StandingRow]:
    """The table, sorted the way the league is: record first, then points."""
    ordered = sorted(state.rosters, key=lambda r: (-(r.wins), -(r.points_for)))
    return [
        StandingRow(
            rank=i,
            name=state.team_name(r),
            record=r.record,
            points=f"{r.points_for:.2f}",
            team_id=str(r.roster_id),
            is_mine=r.roster_id == state.roster.roster_id,
        )
        for i, r in enumerate(ordered, start=1)
    ]


def matches(state: Week, games: Sequence[Game], played: Mapping[str, ScoreboardGame]) -> list[Match]:
    """The real games a fantasy week is made of, each kicked-off one with its score and where it stands, by club.

    The whole slate rather than only the clubs you hold: which of them matters
    changes with every waiver, and it is one cached request either way.
    """
    mine = {p.team for p in state.projected}
    rows = []
    for game in games:
        board = played.get(game.home)
        rows.append(
            Match(
                label=day(game.date),
                home=game.home,
                away=game.away,
                # Whether you have anyone in it, which is the only thing that makes
                # one game on a Sunday slate different from another.
                detail=" · ".join(
                    part
                    for part in (
                        board.label if board else "",
                        "you have players" if {game.home, game.away} & mine else "",
                    )
                    if part
                ),
                tone="good" if {game.home, game.away} & mine else "neutral",
                home_score=board.home_score if board else None,
                away_score=board.away_score if board else None,
            )
        )
    return rows


def _activity(client: NFLSource, state: Week) -> list[ActivityRow]:
    """What the league has done lately, newest first.

    Bounded to the last few weeks rather than the season: this is "what did I
    miss", and a hundred rows of September waivers is not that.
    """
    by_roster = {r.roster_id: r for r in state.rosters}
    dated: list[tuple[int, ActivityRow]] = []
    for week in range(max(1, state.week - ACTIVITY_WEEKS + 1), state.week + 1):
        try:
            transactions = client.get_transactions(state.league.league_id, week)
        except PlatformError as e:
            logger.warning(f"Skipping week {week} activity: {e}")
            continue
        dated.extend(_activity_rows(transactions, state, by_roster))
    # Sorted on the instant, not on the string that renders it: "Sep 3" sorts
    # before "Sep 21" alphabetically and after it in time.
    return [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)]


def _activity_rows(
    transactions: Sequence[LeagueMove], state: Week, by_roster: Mapping[int, Team]
) -> list[tuple[int, ActivityRow]]:
    rows: list[tuple[int, ActivityRow]] = []
    for t in transactions:
        roster = by_roster.get(t.roster_ids[0]) if t.roster_ids else None
        moved = [f"+{_name_of(pid, state)}" for pid in t.adds] + [f"-{_name_of(pid, state)}" for pid in t.drops]
        moves = [_move(pid, "added", by_roster.get(rid), state) for pid, rid in t.adds.items()] + [
            _move(pid, "dropped", by_roster.get(rid), state) for pid, rid in t.drops.items()
        ]
        rows.append(
            (
                t.when,
                ActivityRow(
                    when=moment(t.when),
                    who=state.names.get(roster.owner_id, "") if roster else "",
                    what=TRANSACTION_LABELS.get(t.kind, t.kind),
                    detail=", ".join(moved),
                    is_mine=bool(roster) and roster.roster_id == state.roster.roster_id,
                    moves=moves,
                    bid=f"${t.bid}" if t.bid else "",
                ),
            )
        )
    return rows


def _move(player_id: str, change: Literal["added", "dropped"], team: Team | None, state: Week) -> ActivityMove:
    """One player a move moved, as his own row reads him: a player the catalog has never heard of keeps his id."""
    meta = state.players.get(player_id)
    return ActivityMove(
        player_id=player_id,
        player=meta.name if meta else player_id,
        position=meta.position if meta else "",
        team=meta.team if meta else "",
        change=change,
        manager=state.team_name(team) if team else "",
    )


def _name_of(player_id: str, state: Week) -> str:
    meta = state.players.get(player_id)
    return meta.name if meta else player_id


# ── the rest of the season, for the simulation ──────────────────────────

DEFAULT_SPREAD = 25.0
"""A team's week-to-week spread, in points, before it has played enough weeks to measure one.
About what a fantasy football team's scores scatter by."""

MIN_WEEKS_FOR_SPREAD = 3
"""Played weeks the league needs before its own spread replaces the default."""

DEFAULT_MISS_RATE = 0.12
"""How often a regular starter misses a week, before the league has played enough to measure it:
about what this league measured after seven weeks."""

MIN_MISS_CHANCES = 200
"""Games regulars were there to miss before the league's own rate replaces the default."""

DEFAULT_STRENGTH_ERROR = 8.0
"""How far a team's real strength may sit from its projection, before the league has
played enough weeks to measure it: about what this league measured after six weeks."""


@dataclass(frozen=True)
class SeasonModel:
    """The season ready to simulate, and what it was built from.

    Kept together so a trade can rebuild two teams' rows the same way the
    season built them: the same weeks' projections, the same rescaling, the
    same spread.
    """

    season: SeasonInput
    rosters: Sequence[Team]
    projections: Mapping[int, Mapping[str, Projection]]
    """Each remaining week's projections, by week."""
    scale: float
    spread: float
    miss_rate: float
    """The chance a regular starter misses any one week."""
    live: bool = False
    """Whether this week's rows are its score so far and what each lineup has left, rather than a
    projection: a roster changed now changes only the weeks after it."""

    def mean(self, state: Week, player_ids: Iterable[str], week: int) -> float:
        """What a roster of these players is expected to score in `week`: its best lineup, less what
        its starters' missed weeks cost it, rescaled."""
        return _expected_lineup(state, player_ids, self.projections[week], self.miss_rate) * self.scale


def season_input(client: NFLSource, state: Week, seed: int, scoreboard: Scoreboard | None = None) -> SeasonInput | None:
    """The regular season from this week to its last, ready to simulate.

    None in the playoffs, or where the league says nothing about them.
    """
    model = season_model(client, state, seed, scoreboard)
    return model.season if model else None


def season_model(client: NFLSource, state: Week, seed: int, scoreboard: Scoreboard | None = None) -> SeasonModel | None:
    """The regular season from this week to its last, with what it was built from.

    Each team's mean for a week is the best lineup its roster projects that
    week — which sees byes and injuries coming — less what the weeks its
    starters will miss without warning cost it, rescaled so the league's
    projected average matches what it has actually been scoring, since
    projections run short of what managers score and the points already
    banked are real points. The spread is the league's own: how far teams
    have scored from their averages so far.

    Once this week is under way, with `scoreboard`, every team's week is what
    it has scored plus what its set lineup has left to play, its range
    narrowing as its games run out: so every team's chance, not only yours,
    counts the week as it is going.
    """
    league = state.league
    if not league.playoff_teams or not league.playoff_week_start or state.week >= league.playoff_week_start:
        return None
    remaining = list(range(state.week, league.playoff_week_start))
    rosters = state.rosters

    by_week = client.get_matchups_bulk(league.league_id, remaining)
    # A week that would not load raises why: a season simulated without one
    # week's games is a table nobody will finish in.
    fixtures = [
        Fixture(week=week, home=str(home.roster_id), away=str(away.roster_id))
        for week in remaining
        for home, away in pairings(by_week.value(week))
    ]

    projections = {
        week: client.get_projections(state.season, week, league.scoring_format, FANTASY_POSITIONS, league.scoring_rules)
        for week in remaining
    }
    miss_rate = _miss_rate(client, state)
    projected = {
        (str(roster.roster_id), week): _expected_lineup(state, active(roster), projections[week], miss_rate)
        for week in remaining
        for roster in rosters
    }
    scale = _scale(rosters, projected, state.week)
    spread = _spread(client, league.league_id, state.week)
    strength_error = _strength_error(rosters, projected, scale, spread, state.week)
    so_far = _so_far(state, scoreboard) if scoreboard else {}
    season = SeasonInput(
        teams=tuple(
            TeamRecord(
                team_id=str(r.roster_id),
                name=state.team_name(r),
                wins=r.wins,
                losses=r.losses,
                ties=r.ties,
                points_for=r.points_for,
            )
            for r in rosters
        ),
        fixtures=tuple(fixtures),
        scoring=tuple(
            _going(team, so_far[team], scale, spread)
            if week == state.week and team in so_far
            else TeamWeek(team_id=team, week=week, mean=points * scale, spread=spread)
            for (team, week), points in projected.items()
        ),
        spots=league.playoff_teams,
        mine=str(state.roster.roster_id),
        week=state.week,
        strength_error=strength_error,
        seed=seed,
    )
    return SeasonModel(
        season=season,
        rosters=rosters,
        projections=projections,
        scale=scale,
        spread=spread,
        miss_rate=miss_rate,
        live=bool(so_far),
    )


@dataclass(frozen=True)
class SoFar:
    """One team's week while it is being played."""

    week: int
    scored: float
    """Points on the board, as the platform has them."""
    left: float
    """What its starters are projected to add in what is left of their games."""
    full: float
    """What its starters were projected for the whole week."""


def _so_far(state: Week, scoreboard: Scoreboard) -> dict[str, SoFar]:
    """Each team's week once its games are under way; none before the first kickoff.

    Before then the set lineup is no better a guess than the best one, which
    a manager has days left to set.
    """
    live = scoreboard.live(state)
    if not live.under_way:
        return {}
    board = scoreboard.board(state)

    def left(club: str) -> float:
        if club in board:
            return left_in(board[club])
        return UNDER_WAY if club in live.started else 1.0

    scored = {entry.roster_id: entry.points for entry in state.matchups}
    so_far: dict[str, SoFar] = {}
    for roster in state.rosters:
        if roster.roster_id not in scored:
            continue
        starters = projections_for([pid for pid in roster.starter_ids if pid], state.projections, state.players)
        so_far[str(roster.roster_id)] = SoFar(
            week=state.week,
            scored=scored[roster.roster_id],
            left=sum(p.points * left(p.team) for p in starters),
            full=sum(p.points for p in starters),
        )
    return so_far


def _going(team: str, so_far: SoFar, scale: float, spread: float) -> TeamWeek:
    """A week under way as the season plays it: the points banked, and the rest around its projection.

    What is left is rescaled as a whole week would be; what is banked is real.
    The range shrinks with the square root of the share left, as a sum of
    independent plays does, to none once its games are over.
    """
    share = so_far.left / so_far.full if so_far.full else 0.0
    return TeamWeek(
        team_id=team,
        week=so_far.week,
        mean=so_far.scored + so_far.left * scale,
        spread=spread * math.sqrt(share),
    )


def _expected_lineup(
    state: Week, player_ids: Iterable[str], projections: Mapping[str, Projection], miss_rate: float
) -> float:
    """What a roster's best lineup is expected to score once any regular starter may miss the week.

    Each starter misses at the league's own rate, and the bench covers for him
    as it would: the week costs what his lineup scores without him. That is
    what prices a backup, whom a best lineup alone counts as nothing. Two out
    at once is rare enough to leave out; a kicker or a defense does not miss.
    """
    held = list(player_ids)
    lineup = lineup_for(state, held, projections)
    full = lineup_points(lineup)
    starters = [
        slot.player.player_id
        for slot in lineup
        if slot.player and slot.player.points > 0 and slot.player.position in SNAP_POSITIONS
    ]
    if not starters:
        return full
    chance = min(miss_rate, 1 / len(starters))
    cost = sum(
        full - lineup_points(lineup_for(state, [pid for pid in held if pid != out], projections)) for out in starters
    )
    return full - chance * cost


def _miss_rate(client: NFLSource, state: Week) -> float:
    """How often the league's regular starters have missed a week this season, or the default before it can say."""
    played = weeks_played(state.week, state.is_regular_season)
    if not played:
        return DEFAULT_MISS_RATE
    missed, chances = misses(
        season_lines(
            client.get_nfl_game_lines(
                state.season, played, FANTASY_POSITIONS, state.league.scoring_format, state.league.scoring_rules
            ).values
        )
    )
    return missed / chances if chances >= MIN_MISS_CHANCES else DEFAULT_MISS_RATE


def _scale(rosters: Sequence[Team], projected: dict[tuple[str, int], float], week: int) -> float:
    """What the league actually scores per team-week, over what this week's best lineups project."""
    played = week - 1
    this_week = [points for (_, w), points in projected.items() if w == week]
    if played < 1 or not this_week or not sum(this_week):
        return 1.0
    actual = sum(r.points_for for r in rosters) / (len(rosters) * played)
    # Nothing banked yet is a scoreboard that has not loaded, not a league of noughts.
    return actual / (sum(this_week) / len(this_week)) if actual else 1.0


def _spread(client: NFLSource, league_id: str, week: int) -> float:
    """How far a team's week has fallen from its own average, pooled across the league, over the weeks that load."""
    played = list(range(1, week))
    if len(played) < MIN_WEEKS_FOR_SPREAD:
        return DEFAULT_SPREAD
    by_week = client.get_matchups_bulk(league_id, played).values
    weeks = len(by_week)
    if weeks < MIN_WEEKS_FOR_SPREAD:
        return DEFAULT_SPREAD
    scores: dict[str, list[float]] = {}
    for entries in by_week.values():
        for entry in entries:
            scores.setdefault(str(entry.roster_id), []).append(entry.points)
    deviations = [s - statistics.fmean(v) for v in scores.values() if len(v) > 1 for s in v]
    if len(deviations) < 2:
        return DEFAULT_SPREAD
    # Corrected for each team's average being measured from the same few weeks,
    # which pulls every deviation toward nought.
    return statistics.pstdev(deviations) * (weeks / (weeks - 1)) ** 0.5


def _strength_error(
    rosters: Sequence[Team], projected: dict[tuple[str, int], float], scale: float, spread: float, week: int
) -> float:
    """How far teams' real strength sits from their projected best lineups.

    Each team's average so far, against what its roster projects now: the gap
    is partly that average's own luck — a few weeks of a spread this wide —
    and the rest is the projection being wrong about the team. Only the rest
    is strength the simulation is unsure of.
    """
    played = week - 1
    if played < MIN_WEEKS_FOR_SPREAD:
        return DEFAULT_STRENGTH_ERROR
    gaps = [
        r.points_for / played - projected[(str(r.roster_id), week)] * scale
        for r in rosters
        if (str(r.roster_id), week) in projected
    ]
    if len(gaps) < 2:
        return DEFAULT_STRENGTH_ERROR
    luck = spread**2 / played
    return max(0.0, statistics.pvariance(gaps) - luck) ** 0.5
