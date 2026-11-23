"""One player's matchup week, as the NBA drawer shows it on Yahoo: his games left, his fixtures, his reading
on the to-do list's own scale, and what his next opponent allows his position.
"""

import logging
from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.nba import defense, drawer, views
from thefrontoffice.adapters.outbound.competitions.nba import worth as nba_worth
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.rules import playable_from
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import reads, weighing
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.feeds import Feeds
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)


def week_of(
    feeds: Feeds,
    yahoo: YahooSource,
    league: YahooLeague,
    player: Player,
    reports: Sequence[InjuryReport],
    weights: Mapping[str, float] | None,
    profile: PlayerMeta | None,
) -> tuple[drawer.DrawerWeek, nba_worth.Valuer | None] | None:
    """His matchup week as the drawer shows it, and what a game is worth on the week's scale; None without one.

    Counted as his row counts it (`Feeds.playable`): none while ruled out, or from
    his return. Weighed on the to-do list's own pool (`weighing.valued`), so the
    value it shows is the one his row shows. Each part is enrichment:
    whatever will not load is left out, and the rest stands.
    """
    week = league.current_week
    if not week:
        return None
    try:
        found = yahoo.pairing(yahoo.get_user_team().team_key, week)
    except FrontOfficeError as e:
        logger.warning(f"Showing {player.name} without his week: {e}")
        return None
    if found is None:
        return None
    start, end = found.start, found.end
    back = reads.returns([player], reports).get(player.player_key)
    clubs = feeds.games.get_remaining_games_bulk([player.team], start, end)
    games = feeds.playable(player, clubs, back, end)
    provisional = bool(feeds.games.unscheduled(start, end))
    club = player.team.upper()
    # A claim's games are those from the day he clears waivers, as `Feeds.playable` counts them.
    claimed = playable_from(player)
    after = claimed.isoformat() if claimed else ""
    try:
        fixtures = [g for g in feeds.games.games_left(start, end) if club in (g.home, g.away) and g.date >= after]
    except FrontOfficeError as e:
        logger.warning(f"Showing {player.name}'s week without its games: {e}")
        fixtures = []
    projections = index_for(feeds.sleeper, start, end)
    stats = feeds.form.get_player_stats(player.name)
    projected = projections.find(player.name, player.team, stats) if projections else None
    value = weighing.week_valuer(feeds, yahoo, weights, found)
    reading = nba_worth.read(player, stats, projected, value, games, provisional, back) if value else None
    matchup = None
    if fixtures and profile:
        opponent = fixtures[0].away if fixtures[0].home == club else fixtures[0].home
        matchup = defense.allowed(feeds.form.box_scores(), weights).get((opponent, profile.position))
    left = views.counted(games, provisional)
    return drawer.DrawerWeek(left, fixtures, reading, projected, matchup), value
