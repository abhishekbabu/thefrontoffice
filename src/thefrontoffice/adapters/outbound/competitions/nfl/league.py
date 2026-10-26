"""The league beyond this week: the season, the table, the real games, the moves.

Separate from the week because it answers a different question asked at a
different time — how the season is going, rather than what to do about Sunday —
and it costs requests the week does not need. Nobody checking a lineup should
wait on eighteen weeks of matchups.
"""

import logging
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from thefrontoffice.adapters.outbound.competitions import places
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import lineup_points, optimal_lineup
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Week,
    day,
    games_by_week,
    moment,
    projection_for,
    week_dates,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import SleeperRoster, Transaction, WeeklyProjection
from thefrontoffice.domain.errors import SleeperAPIError
from thefrontoffice.domain.models import (
    ActivityRow,
    Fixture,
    LeagueSchedule,
    Match,
    ScheduleRow,
    SeasonInput,
    StandingRow,
    Stat,
    TeamRecord,
    TeamWeek,
    Tone,
)

logger = logging.getLogger(__name__)

REGULAR_SEASON_WEEKS = 18

# "What did I miss", not the season's whole transaction log.
ACTIVITY_WEEKS = 3

TRANSACTION_LABELS = {
    "waiver": "Waiver",
    "free_agent": "Free agent",
    "trade": "Trade",
    "commissioner": "Commissioner",
}


def build(client: SleeperNFLSource, state: Week, league_id: str) -> LeagueSchedule:
    """The season, the table, this week's real games, and what the league did."""
    rosters = client.get_rosters(league_id)
    names = client.get_league_users(league_id)
    by_roster = {r.roster_id: r for r in rosters}

    standings = _standings(state, rosters, names)
    return LeagueSchedule(
        headline=_headline(state, standings),
        season=_season_rows(client, state, league_id, by_roster, names),
        standings=standings,
        matches=_matches(client, state),
        activity=_activity(client, state, league_id, by_roster, names),
    )


def _season_rows(
    client: SleeperNFLSource,
    state: Week,
    league_id: str,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[ScheduleRow]:
    """Your own season, week by week, with who you play and how it went.

    Eighteen matchup fetches, run concurrently and cached — asked one at a
    time they are the whole wait on the page.
    """
    games = games_by_week(client, state.season)
    weeks = list(range(1, _last_week(state) + 1))
    try:
        by_week = client.get_matchups_bulk(league_id, weeks)
    except SleeperAPIError as e:
        logger.warning(f"Continuing without the season's matchups: {e}")
        by_week = {}

    rows: list[ScheduleRow] = []
    for week in weeks:
        matchups = by_week.get(week, [])
        mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
        theirs = _other_side(matchups, mine, state.roster.roster_id)
        opponent = by_roster.get(int(theirs.get("roster_id", 0))) if theirs else None

        playoff = _playoff_round(state, week)
        if playoff and week > state.week:
            # Sleeper fills the bracket weeks with placeholder pairings until
            # the regular season ends; a name there is not who you will play.
            opponent = None
        rows.append(
            ScheduleRow(
                label=f"Week {week}",
                date=week_dates(games.get(week, [])),
                opponent=names.get(opponent.owner_id, "") if opponent else "",
                detail=playoff or (opponent.record if opponent else "bye"),
                result=_result(mine, theirs, week, state.week),
                tone=_week_tone(mine, theirs, week, state.week),
                is_current=week == state.week,
                playoffs=bool(playoff),
            )
        )
    return rows


def _last_week(state: Week) -> int:
    """The league's final week: the end of its playoffs, or the NFL's last where it names none."""
    start, teams = state.league.playoff_week_start, state.league.playoff_teams
    if not start or not teams:
        return REGULAR_SEASON_WEEKS
    return min(REGULAR_SEASON_WEEKS, start + math.ceil(math.log2(teams)) - 1)


def _playoff_round(state: Week, week: int) -> str:
    """'Playoffs, round 1' for a bracket week; empty for the regular season."""
    start = state.league.playoff_week_start
    return f"Playoffs, round {week - start + 1}" if start and week >= start else ""


def _headline(state: Week, standings: list[StandingRow]) -> list[Stat]:
    """Your season in figures: the record, where it puts you, and the points behind it."""
    place = next((row.rank for row in standings if row.is_mine), 0)
    stats = [Stat(label="Record", value=state.roster.record)]
    if place:
        stats.append(Stat(label="Place", value=places.place(place, len(standings))))
    return [*stats, Stat(label="Points for", value=f"{state.roster.points_for:.1f}")]


def _other_side(matchups: list[dict[str, Any]], mine: dict[str, Any] | None, roster_id: int) -> Any:
    if not mine or mine.get("matchup_id") is None:
        return None
    return next(
        (m for m in matchups if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster_id),
        None,
    )


def _result(mine: Any, theirs: Any, week: int, current: int) -> str:
    """The score, and only once there is one. A future week is not 0-0."""
    if week >= current or not mine or not theirs:
        return ""
    return f"{float(mine.get('points') or 0):.1f}-{float(theirs.get('points') or 0):.1f}"


def _week_tone(mine: Any, theirs: Any, week: int, current: int) -> Tone:
    if week >= current or not mine or not theirs:
        return "neutral"
    return "good" if float(mine.get("points") or 0) > float(theirs.get("points") or 0) else "warning"


def _standings(state: Week, rosters: list[SleeperRoster], names: dict[str, str]) -> list[StandingRow]:
    """The table, sorted the way the league is: record first, then points."""
    ordered = sorted(rosters, key=lambda r: (-(r.wins), -(r.points_for)))
    return [
        StandingRow(
            rank=i,
            name=names.get(r.owner_id, f"Roster {r.roster_id}"),
            record=r.record,
            points=f"{r.points_for:.1f}",
            team_id=str(r.roster_id),
            is_mine=r.roster_id == state.roster.roster_id,
        )
        for i, r in enumerate(ordered, start=1)
    ]


def _matches(client: SleeperNFLSource, state: Week) -> list[Match]:
    """The real games this fantasy week is made of.

    The whole slate rather than only the clubs you hold: which of them matters
    changes with every waiver, and it is one cached request either way.
    """
    games = games_by_week(client, state.season).get(state.week, [])
    mine = {p.team for p in state.projected}
    return [
        Match(
            label=day(game.date),
            home=game.home,
            away=game.away,
            # Whether you have anyone in it, which is the only thing that makes
            # one game on a Sunday slate different from another.
            detail="you have players" if {game.home, game.away} & mine else "",
            tone="good" if {game.home, game.away} & mine else "neutral",
        )
        for game in games
    ]


def _activity(
    client: SleeperNFLSource,
    state: Week,
    league_id: str,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[ActivityRow]:
    """What the league has done lately, newest first.

    Bounded to the last few weeks rather than the season: this is "what did I
    miss", and a hundred rows of September waivers is not that.
    """
    dated: list[tuple[int, ActivityRow]] = []
    for week in range(max(1, state.week - ACTIVITY_WEEKS + 1), state.week + 1):
        try:
            transactions = client.get_transactions(league_id, week)
        except SleeperAPIError as e:
            logger.warning(f"Skipping week {week} activity: {e}")
            continue
        dated.extend(_activity_rows(transactions, state, by_roster, names))
    # Sorted on the instant, not on the string that renders it: "Sep 3" sorts
    # before "Sep 21" alphabetically and after it in time.
    return [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)]


def _activity_rows(
    transactions: list[Transaction],
    state: Week,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[tuple[int, ActivityRow]]:
    rows: list[tuple[int, ActivityRow]] = []
    for t in transactions:
        roster = by_roster.get(t.roster_ids[0]) if t.roster_ids else None
        moved = [f"+{_name_of(pid, state)}" for pid in t.adds] + [f"-{_name_of(pid, state)}" for pid in t.drops]
        rows.append(
            (
                t.when,
                ActivityRow(
                    when=moment(t.when),
                    who=names.get(roster.owner_id, "") if roster else "",
                    what=TRANSACTION_LABELS.get(t.kind, t.kind),
                    detail=", ".join(moved),
                    tone="good" if roster and roster.roster_id == state.roster.roster_id else "neutral",
                ),
            )
        )
    return rows


def _name_of(player_id: str, state: Week) -> str:
    meta = state.players.get(player_id)
    return str(meta.get("name") or player_id) if meta else player_id


# ── the rest of the season, for the simulation ──────────────────────────

DEFAULT_SPREAD = 25.0
"""A team's week-to-week spread, in points, before it has played enough weeks to measure one.
About what a fantasy football team's scores scatter by."""

MIN_WEEKS_FOR_SPREAD = 3
"""Played weeks the league needs before its own spread replaces the default."""

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
    rosters: list[SleeperRoster]
    projections: dict[int, dict[str, WeeklyProjection]]
    """Each remaining week's projections, by week."""
    scale: float
    spread: float

    def mean(self, state: Week, player_ids: Iterable[str], week: int) -> float:
        """What a roster of these players is expected to score in `week`: its best lineup, rescaled."""
        return _best_lineup(state, player_ids, self.projections[week]) * self.scale


def season_input(client: SleeperNFLSource, state: Week, league_id: str, seed: int) -> SeasonInput | None:
    """The regular season from this week to its last, ready to simulate.

    None in the playoffs, or where the league says nothing about them.
    """
    model = season_model(client, state, league_id, seed)
    return model.season if model else None


def season_model(client: SleeperNFLSource, state: Week, league_id: str, seed: int) -> SeasonModel | None:
    """The regular season from this week to its last, with what it was built from.

    Each team's mean for a week is the best lineup its roster projects that
    week — which sees byes and injuries coming — rescaled so the league's
    projected average matches what it has actually been scoring, since
    projections run short of what managers score and the points already
    banked are real points. The spread is the league's own: how far teams
    have scored from their averages so far.
    """
    league = state.league
    if not league.playoff_teams or not league.playoff_week_start or state.week >= league.playoff_week_start:
        return None
    remaining = list(range(state.week, league.playoff_week_start))
    rosters = client.get_rosters(league_id)
    names = client.get_league_users(league_id)

    fixtures = []
    for week, entries in client.get_matchups_bulk(league_id, remaining).items():
        paired: dict[Any, list[str]] = {}
        for entry in entries:
            if entry.get("matchup_id") is not None:
                paired.setdefault(entry["matchup_id"], []).append(str(entry.get("roster_id")))
        fixtures += [Fixture(week=week, home=pair[0], away=pair[1]) for pair in paired.values() if len(pair) == 2]

    projections = {week: client.get_projections(state.season, week, league.scoring_format) for week in remaining}
    projected = {
        (str(roster.roster_id), week): _best_lineup(state, roster.player_ids, projections[week])
        for week in remaining
        for roster in rosters
    }
    scale = _scale(rosters, projected, state.week)
    spread = _spread(client, league_id, state.week)
    strength_error = _strength_error(rosters, projected, scale, spread, state.week)
    season = SeasonInput(
        teams=tuple(
            TeamRecord(
                team_id=str(r.roster_id),
                name=names.get(r.owner_id, f"Roster {r.roster_id}"),
                wins=r.wins,
                losses=r.losses,
                ties=r.ties,
                points_for=r.points_for,
            )
            for r in rosters
        ),
        fixtures=tuple(fixtures),
        scoring=tuple(
            TeamWeek(team_id=team, week=week, mean=points * scale, spread=spread)
            for (team, week), points in projected.items()
        ),
        spots=league.playoff_teams,
        mine=str(state.roster.roster_id),
        week=state.week,
        strength_error=strength_error,
        seed=seed,
    )
    return SeasonModel(season=season, rosters=rosters, projections=projections, scale=scale, spread=spread)


def _best_lineup(state: Week, player_ids: Iterable[str], projections: dict[str, WeeklyProjection]) -> float:
    players = [p for p in (projection_for(pid, projections, state.players) for pid in player_ids) if p]
    return lineup_points(optimal_lineup(state.league.starting_slots, players))


def _scale(rosters: list[SleeperRoster], projected: dict[tuple[str, int], float], week: int) -> float:
    """What the league actually scores per team-week, over what this week's best lineups project."""
    played = week - 1
    this_week = [points for (_, w), points in projected.items() if w == week]
    if played < 1 or not this_week or not sum(this_week):
        return 1.0
    actual = sum(r.points_for for r in rosters) / (len(rosters) * played)
    # Nothing banked yet is a scoreboard that has not loaded, not a league of noughts.
    return actual / (sum(this_week) / len(this_week)) if actual else 1.0


def _spread(client: SleeperNFLSource, league_id: str, week: int) -> float:
    """How far a team's week has fallen from its own average, pooled across the league."""
    played = list(range(1, week))
    if len(played) < MIN_WEEKS_FOR_SPREAD:
        return DEFAULT_SPREAD
    scores: dict[str, list[float]] = {}
    for entries in client.get_matchups_bulk(league_id, played).values():
        for entry in entries:
            scores.setdefault(str(entry.get("roster_id")), []).append(float(entry.get("points") or 0))
    deviations = [s - statistics.fmean(v) for v in scores.values() if len(v) > 1 for s in v]
    if len(deviations) < 2:
        return DEFAULT_SPREAD
    # Corrected for each team's average being measured from the same few weeks,
    # which pulls every deviation toward nought.
    weeks = len(played)
    return statistics.pstdev(deviations) * (weeks / (weeks - 1)) ** 0.5


def _strength_error(
    rosters: list[SleeperRoster], projected: dict[tuple[str, int], float], scale: float, spread: float, week: int
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
