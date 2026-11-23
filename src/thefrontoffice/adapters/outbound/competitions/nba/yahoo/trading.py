"""Trades in NBA on Yahoo: one proposal priced for the scout, and the season's market of trades near even.

Each reads the league through the provider's readers (`feeds`, a league's
`yahoo`); the market searches on the rosters' week (`weighing.read_week`) and
every week left (`market.build`).
"""

import logging
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions.nba import forecast as nba_forecast
from thefrontoffice.adapters.outbound.competitions.nba import league as nba_league
from thefrontoffice.adapters.outbound.competitions.nba import market as nba_market
from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba import strength as nba_strength
from thefrontoffice.adapters.outbound.competitions.nba.context import PlayerContextBuilder
from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC, amount
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import reads, weighing
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.feeds import Feeds
from thefrontoffice.adapters.outbound.competitions.seeds import seed
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource, once
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import CompetitionContext, TeamRecord, TradeMarket, TradeProposal

logger = logging.getLogger(__name__)


def context(feeds: Feeds, yahoo: YahooSource, league: YahooLeague, proposal: TradeProposal) -> CompetitionContext:
    """Price both sides of a trade against the current roster, in the league's own scoring."""
    weights = reads.weights(league, yahoo)
    builder = PlayerContextBuilder(feeds.form, feeds.games, weights)
    giving, receiving = resolve_sides(proposal, lambda name: reads.find_player(yahoo, name))

    my_team = yahoo.get_user_team()
    week = yahoo.get_matchup(my_team.team_key)

    # Not enrichment: a trade is judged against the roster it changes, and
    # one judged without it is an answer to a different question.
    rostered = yahoo.roster(my_team.team_key)
    returns = reads.returns([*rostered, *giving, *receiving], feeds.reports())
    roster = builder.build_player_lines(
        rostered, week.start if week else None, week.end if week else None, returns=returns
    )

    text = prompt.trade(
        giving=builder.build_context_for_players(giving, returns=returns),
        receiving=builder.build_context_for_players(receiving, returns=returns),
        week=week,
        roster="".join(roster.values()),
        weights=weights,
    )
    return CompetitionContext(prompt=text, situation=prompt.matchup(week, weights), roster_lines=roster)


def market(feeds: Feeds, yahoo: YahooSource, league: YahooLeague) -> TradeMarket | None:
    """The rest of the season, and every trade near even in worth that improves your weeks (`market.build`).

    None between seasons, once the regular season is over, and past the
    trade deadline the league's settings name. A category league is
    searched where a week counts as one win (Yahoo's "H2H Cat One"), which
    is what its table and the season's simulation count.

    Raises:
        UnsupportedError: a league whose table counts every category, scores only a best game, or whose points
            settings carry no weights.
        PlatformError: the schedule would not load.
    """
    current = league.current_week
    if not current:
        return None
    rules = yahoo.settings()
    if not rules.playoff_start_week or current >= rules.playoff_start_week:
        return None
    if rules.trade_end is not None and datetime.now(PACIFIC).date() > rules.trade_end:
        return None
    categories = reads.judged_on(league, rules)
    mine = yahoo.get_user_team().team_key
    standings = yahoo.standings()
    drawn = yahoo.matchups(list(range(current, league.last_week(current) + 1)))
    dates = nba_league.week_dates(drawn)
    if current not in dates:
        return None
    rosters = yahoo.rosters([team.team_key for team in standings])
    try:
        wire = reads.wire(yahoo, reads.STREAM_DEPTH)
    except FrontOfficeError as e:
        logger.warning(f"Pricing trades without the wire, which would not load: {e}")
        wire = []
    players = once(p for roster in [*rosters.values(), wire] for p in roster)
    weights = reads.weights(league, yahoo)
    start, end = dates[current]
    readings = weighing.read_week(feeds, yahoo, weights, players, start, end)
    returns = reads.returns(players, feeds.reports())
    weeks = [
        nba_market.Week(
            week=week,
            days={p.player_key: frozenset(nba_strength.nights(p, games, returns.get(p.player_key))) for p in players},
            pairs=[(found.mine.team_key, found.opponent.team_key) for found in drawn.get(week, [])],
        )
        for week, (first, last) in sorted(dates.items())
        for games in [
            feeds.games.games_left(first, last) if week == current else feeds.games.games_between(first, last)
        ]
    ]
    this_week = {
        side.team_key: nba_strength.banked(side, categories, points=weights is not None)
        for found in drawn.get(current, [])
        for side in (found.mine, found.opponent)
    }
    return nba_market.build(
        nba_market.League(
            mine=mine,
            teams=[
                TeamRecord(t.team_key, t.name, s.wins, s.losses, s.ties, amount(s.points_for))
                for t in standings
                if (s := t.standing) is not None
            ],
            rosters=rosters,
            profiles={
                key: nba_strength.profile(reading, feeds.recent(reading.player), weights)
                for key, reading in readings.items()
            },
            weeks=weeks,
            playoff_start=rules.playoff_start_week,
            spots=rules.playoff_teams,
            slots=rules.starting or nba_forecast.active_slots(*rosters.values()),
            roster_size=rules.roster_size,
            categories=categories,
            banked=this_week,
            wire=wire,
            weekly=rules.weekly_lineups,
            deadline=rules.trade_end,
            seed=seed(league.league_key, current),
        )
    )
