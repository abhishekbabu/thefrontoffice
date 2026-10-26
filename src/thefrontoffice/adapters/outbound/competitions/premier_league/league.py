"""The league beyond this gameweek: the season, the table, the real matches.

Separate from the gameweek because it answers a different question asked at a
different time — how the season is going, rather than what to do before the
deadline — and it costs requests the week does not need.

No activity section: FPL publishes no transfer feed for a mini-league, and a
tab that is always empty is worse than one that is not there.
"""

import logging

from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import H2HMatch, MiniLeague
from thefrontoffice.domain.models import LeagueSchedule, Match, ScheduleRow, StandingRow, Tone

logger = logging.getLogger(__name__)

# FPL's own scale runs 1-5; 4 is where its UI starts calling a run hard.
HARD_FIXTURE = 4


def build(client: FPLSource, league: MiniLeague | None, entry_id: int, playing: int) -> LeagueSchedule:
    """The season, the table, and the real matches behind the gameweek.

    The matches stand on their own: they are the gameweek itself, and they are
    the same whether or not this id names a league with fixtures to read.
    """
    if league is None:
        return LeagueSchedule(matches=_matches(client, playing))
    return LeagueSchedule(
        season=_season_rows(client, league, entry_id, playing),
        standings=_standings(client, league, entry_id),
        matches=_matches(client, playing),
    )


def _season_rows(client: FPLSource, league: MiniLeague, entry_id: int, playing: int) -> list[ScheduleRow]:
    """Your gameweeks, with the tie in each where the league has one.

    A classic league has no season in this sense — it is a running table,
    not a set of fixtures — so it gets the gameweeks and their deadlines
    without opponents, which is still the calendar somebody came for.
    """
    gameweeks = client.get_gameweeks()
    ties = {}
    if league.is_h2h:
        try:
            ties = client.get_h2h_season(league.id, entry_id)
        except FPLAPIError as e:
            logger.warning(f"Continuing without the h2h season: {e}")

    rows = []
    for gw in gameweeks:
        tie = ties.get(gw.id)
        played = gw.id < playing
        rows.append(
            ScheduleRow(
                label=gw.name,
                date=at_time(gw.deadline) if gw.deadline else "",
                opponent=tie.opponent_name if tie else "",
                detail="" if tie else ("no tie" if league.is_h2h else ""),
                result=f"{tie.my_points}-{tie.opponent_points}" if tie and played else "",
                tone=_tie_tone(tie, played),
                is_current=gw.id == playing,
            )
        )
    return rows


def _tie_tone(tie: H2HMatch | None, played: bool) -> Tone:
    if not tie or not played:
        return "neutral"
    if tie.my_points == tie.opponent_points:
        return "neutral"
    return "good" if tie.my_points > tie.opponent_points else "warning"


def _standings(client: FPLSource, league: MiniLeague, entry_id: int) -> list[StandingRow]:
    try:
        table = client.get_standings(league.id, league.is_h2h)
    except FPLAPIError as e:
        logger.warning(f"Continuing without the table: {e}")
        return []
    return [
        StandingRow(
            rank=row.rank,
            name=row.entry_name,
            detail=row.manager,
            record=row.record,
            # In h2h the table is on league points and the FPL total is the
            # tiebreak; in a classic league they are the same number.
            points=f"{row.total:,}" if not league.is_h2h else f"{row.total} ({row.points_for:,} pts)",
            team_id=str(row.entry),
            is_mine=row.entry == entry_id,
        )
        for row in table
    ]


def _matches(client: FPLSource, gameweek: int) -> list[Match]:
    """The real matches the gameweek is made of, with both difficulties.

    Difficulty is per side, so it is carried per side: a fixture is easy
    for one of these clubs and hard for the other, and one number for the
    match would be true of neither.
    """
    try:
        fixtures = client.get_fixtures(gameweek)
    except FPLAPIError as e:
        logger.warning(f"Continuing without fixtures: {e}")
        return []
    return [
        Match(
            label=at_time(f.kickoff) if f.kickoff else "TBC",
            home=f.home,
            away=f.away,
            detail=f"FDR {f.home_difficulty} / {f.away_difficulty}",
            tone="warning" if max(f.home_difficulty, f.away_difficulty) >= HARD_FIXTURE else "neutral",
        )
        for f in sorted(fixtures, key=lambda f: (f.kickoff is None, f.kickoff))
    ]
