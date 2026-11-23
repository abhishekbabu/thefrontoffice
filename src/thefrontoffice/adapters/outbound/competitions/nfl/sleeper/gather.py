"""What a week is gathered from, read off the clients alone: the matchups, the records before it, the
evidence of the weeks played, ESPN's injury report and news, and who the crowd is adding.

Each read beyond the projections and rosters is enrichment: what will not load leaves the week without it.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from thefrontoffice.adapters.outbound.competitions.injuries import PlayerInjuries
from thefrontoffice.adapters.outbound.competitions.news import PlayerNews
from thefrontoffice.adapters.outbound.competitions.nfl import (
    evidence,
    injuries,
    news,
    prompt,
)
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    FREE_AGENT,
    Phase,
    Trending,
)
from thefrontoffice.adapters.outbound.competitions.nfl.rules import (
    FANTASY_POSITIONS,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import rostered
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    weeks_played,
)
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    SleeperLeague,
    SleeperMatchup,
    SleeperRoster,
)
from thefrontoffice.domain.errors import (
    PlatformError,
)

logger = logging.getLogger(__name__)


def trending(client: SleeperNFLSource) -> Sequence[Trending] | None:
    """Who the crowd is adding; None where it will not load — an independent signal, not load-bearing."""
    try:
        return client.get_trending("add", lookback_hours=prompt.TRENDING_HOURS, limit=prompt.TRENDING_LIMIT)
    except PlatformError as e:
        logger.warning(f"Skipping trending players: {e}")
        return None


def current_week(phase: Phase) -> int:
    """The week the report is about; the opener while still in preseason."""
    return max(1, phase.week if phase.is_regular_season else 1)


def records_before(
    client: SleeperNFLSource, league_id: str, week: int, rosters: list[SleeperRoster], league: SleeperLeague
) -> list[SleeperRoster]:
    """The records as they stood going into `week`; today's where a week before it will not load.

    A count missing a week would be the record of no moment at all; today's
    is at least one the team really had.
    """
    before = client.get_matchups_bulk(league_id, list(range(1, week)))
    if before.failures:
        logger.warning(f"Showing today's records on week {week}: weeks {sorted(before.failures)} would not load")
        return rosters
    return rostered.as_of(rosters, before.values, league)


def matchups(client: SleeperNFLSource, league_id: str, week: int) -> list[SleeperMatchup]:
    """The week's head-to-heads; none where they will not load, which leaves the week without an opponent."""
    try:
        return client.get_matchups(league_id, week)
    except SleeperAPIError as e:
        logger.warning(f"Continuing without the week's matchups, so its opponent, live score and lineups: {e}")
        return []


def season_evidence(
    client: SleeperNFLSource,
    season: str,
    week: int,
    league: SleeperLeague,
    is_regular_season: bool,
    players: Mapping[str, PlayerMeta],
) -> evidence.Evidence:
    """Roles and matchups from every week finished so far that loads."""
    played = weeks_played(week, is_regular_season)
    if not played:
        return evidence.Evidence()
    scoring = league.scoring_format
    lines = evidence.season_lines(
        client.get_nfl_game_lines(season, played, FANTASY_POSITIONS, scoring, league.scoring_rules).values
    )
    out = {pid for pid, meta in players.items() if ruled_out(meta.injury_status)}
    return evidence.gather(lines, scoring, out)


def reports_for(espn_client: ESPNSource, players: dict[str, PlayerMeta], season: str) -> PlayerInjuries:
    """Each player's row on ESPN's injury report as it stands now, where it names him.

    Then, for whoever Sleeper has ruled out and the report has dropped,
    his own latest entry from ESPN.
    """
    try:
        reports = espn_client.get_injuries(espn.NFL)
    except ESPNAPIError as e:
        # Sleeper's own designations stand: older, but still a designation.
        logger.warning(f"Continuing on Sleeper's injury designations alone: {e}")
        return PlayerInjuries()
    espn_ids = {meta.espn_id: pid for pid, meta in players.items() if meta.espn_id}
    found = injuries.matched(reports, players, espn_ids)
    return PlayerInjuries(by_player=found | backfilled(espn_client, players, found, espn_ids, season))


def backfilled(
    espn_client: ESPNSource,
    players: dict[str, PlayerMeta],
    found: dict[str, espn.InjuryReport],
    espn_ids: dict[str, str],
    season: str,
) -> dict[str, espn.InjuryReport]:
    """The latest entry of each player ruled out whom the report has dropped, keyed by Sleeper's id.

    The rosters are read only for a player Sleeper carries no ESPN id for.
    Enrichment like the news: what will not load leaves the report as it was.
    """
    wanted = injuries.unreported(players, found)
    if not wanted:
        return {}
    try:
        roster = espn_client.get_rosters(espn.NFL) if any(not players[pid].espn_id for pid in wanted) else []
        athletes = injuries.athletes(wanted, players, espn_ids, roster)
        entries = espn_client.get_athlete_injuries(espn.NFL, season, list(athletes.values()))
    except ESPNAPIError as e:
        logger.warning(f"Continuing on the injury report alone, without the players it has dropped: {e}")
        return {}
    return {pid: entries[a.athlete_id] for pid, a in athletes.items() if a.athlete_id in entries}


def player_news(espn_client: ESPNSource, players: dict[str, PlayerMeta]) -> PlayerNews:
    """Recent articles about every player, from each club's own feed."""
    clubs = sorted({espn_club(m.team) for m in players.values() if m.team != FREE_AGENT})
    try:
        feeds = espn_client.get_team_news(espn.NFL, clubs)
    except ESPNAPIError as e:
        # Enrichment, like the evidence: the week stands without it.
        logger.warning(f"Continuing without player news: {e}")
        return PlayerNews()
    return news.attach(feeds, players, datetime.now(UTC))
