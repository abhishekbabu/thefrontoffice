"""The scout's prompts for NBA on Yahoo: the week's, and the one asking for a call on each listed free agent.

Each reads the league through the provider's readers (`feeds`, a league's
`yahoo`), and the to-do list off the week weighed (`weighing`), so a line the
model judges is the line every page shows.
"""

import logging
from collections.abc import Sequence

from thefrontoffice.adapters.outbound.competitions import untouchables
from thefrontoffice.adapters.outbound.competitions.nba import actions, prompt
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba import worth as nba_worth
from thefrontoffice.adapters.outbound.competitions.nba.context import (
    PlayerContextBuilder,
    rank_by_points,
    rank_free_agents,
)
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import reads, weighing
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.feeds import Feeds
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import CompetitionContext

logger = logging.getLogger(__name__)


def context(
    feeds: Feeds, yahoo: YahooSource, league: YahooLeague, limit: int, untouchable: frozenset[str] = frozenset()
) -> CompetitionContext:
    """Gather league state and render the scouting prompt, against the league's weekly add `limit`.

    Nobody `untouchable`, by Yahoo key, is a drop, and the model is told so.

    Returns the prompt plus the pieces that make it up, so a follow-up
    briefing can be assembled without re-deriving or re-sending everything.
    """
    weights = reads.weights(league, yahoo)
    my_team = yahoo.get_user_team()
    week = yahoo.get_matchup(my_team.team_key)
    start, end = (week.start, week.end) if week else (None, None)
    used_adds = my_team.adds_used

    # Gathered before the schedule so one bulk lookup covers every team
    # either of them touches.
    rostered = yahoo.roster(my_team.team_key)
    free_agents, annotations = (
        rank_by_points(reads.wire(yahoo), feeds.form.get_player_stats, weights)
        if weights
        else rank_free_agents(yahoo.fetch_top_by_stat(reads.LEADERS, per_stat=reads.LEADERS_PER_STAT))
    )
    logger.debug(f"Building context for {len(rostered)} rostered and {len(free_agents)} free agents")

    remaining_games: dict[str, int] = {}
    if start and end:
        teams = [p.team for p in (*rostered, *free_agents)]
        remaining_games = feeds.games.get_remaining_games_bulk(teams, start, end)

    projections = index_for(feeds.sleeper, start, end)
    reports = feeds.reports()
    returns = reads.returns([*rostered, *free_agents], reports)
    splits = feeds.splits([*rostered, *free_agents], weights, reports)
    decided = (
        weighing.decide(
            feeds,
            yahoo,
            league,
            rostered,
            week.opponent_roster,
            week.start,
            week.end,
            max(0, limit - used_adds),
            free_agents,
            reads.averages(yahoo, my_team.team_key, week.opponent.team_key),
            untouchable=untouchable,
        )
        if week
        else weighing.Decided({}, nba_week.off_il(rostered))
    )
    tasks = decided.actions
    # A pickup the list names is a free agent the model judges, so it reads his line too.
    named = {pid for task in tasks for pid in (task.player_id, task.replaces, task.drop) if pid}
    held = {p.player_key for p in rostered}
    free_agents += [
        r.player
        for key, r in decided.readings.items()
        if key in named and key not in held and all(p.player_key != key for p in free_agents)
    ]
    builder = PlayerContextBuilder(feeds.form, feeds.games, weights)
    roster_lines = builder.build_player_lines(
        rostered,
        start,
        end,
        remaining_games=remaining_games,
        projections=projections,
        returns=returns,
        splits=splits,
        readings=decided.readings,
    )
    fa_lines = builder.build_player_lines(
        free_agents,
        start,
        end,
        annotations,
        remaining_games,
        projections=projections,
        returns=returns,
        splits=splits,
        readings=decided.readings,
    )

    unscheduled = feeds.games.unscheduled(start, end) if start and end else []
    schedule_context = prompt.schedule(
        week, remaining_games, projected=projections is not None, unscheduled=unscheduled
    )
    kept = frozenset(p.name for p in rostered if p.player_key in untouchable)
    trans_context = "\n".join([prompt.transactions(used_adds, limit), *(f"- {n}" for n in untouchables.note(kept))])
    by_key = {p.player_key: p for p in (*rostered, *free_agents)}
    return CompetitionContext(
        prompt=prompt.scout(
            roster="".join(roster_lines.values()),
            week=week,
            free_agents="".join(fa_lines.values()),
            schedule_context=schedule_context,
            trans_context=trans_context,
            adds_left=max(0, limit - used_adds),
            weights=weights,
            tasks=tasks,
        ),
        situation=prompt.matchup(week, weights),
        constraints=trans_context,
        extra=schedule_context,
        roster_lines=roster_lines,
        candidate_lines=fa_lines,
        headline=nba_week.adds(used_adds, limit),
        tasks=tasks,
        # What a game of each is worth, so a model's add never costs a better player than it brings.
        worth={
            r.player.name: game
            for key, r in decided.readings.items()
            if key in by_key and (game := nba_worth.game_value(r)) is not None
        },
        listed=frozenset(by_key[pid].name for pid in named if pid in by_key),
        # A kept judgment's add of somebody another manager has since claimed is no move at all.
        movable=frozenset(p.name for p in (*rostered, *free_agents)),
        untouchable=kept,
    )


def wire_context(
    feeds: Feeds,
    yahoo: YahooSource,
    league: YahooLeague,
    limit: int,
    player_ids: list[str],
    untouchable: frozenset[str] = frozenset(),
) -> CompetitionContext:
    """The prompt asking for one call per listed free agent, against the league's weekly add `limit`.

    Each candidate's line is the scout's — form, status and return, games
    left, projection, teammates out, worth this week — plus the weakest
    player he streams over by the to-do list's margin (`actions.fit`), and
    the id the call has to name. Every figure is read over the same players
    whichever are asked about: the roster, the opponent and the top of the
    wire, as the to-do list reads them, so a call kept against a line is
    checked against that same line on any page.

    Raises:
        PlayerNotFoundError: an id is rostered in this league, or not on the wire.
    """
    weights = reads.weights(league, yahoo)
    team = yahoo.get_user_team()
    rostered = yahoo.roster(team.team_key)
    held = {p.player_key for p in rostered}
    everyone = reads.wire(yahoo)
    available = {p.player_key: p for p in everyone if p.player_key not in held}
    unavailable = [pid for pid in player_ids if pid not in available]
    if unavailable:
        raise PlayerNotFoundError(unavailable)
    candidates = [available[pid] for pid in player_ids]
    week = yahoo.get_matchup(team.team_key)
    reports = feeds.reports()
    known = [*rostered, *everyone]
    returns = reads.returns(known, reports)
    splits = feeds.splits(known, weights, reports)
    readings: dict[str, Reading] = {}
    remaining: dict[str, int] = {}
    start, end = (week.start, week.end) if week else (None, None)
    if week:
        pool = [*rostered, *week.opponent_roster, *reads.wire(yahoo, reads.STREAM_DEPTH)]
        readings = weighing.read_week(
            feeds, yahoo, weights, pool, week.start, week.end, candidates, reads.carried(everyone)
        )
        remaining = feeds.games.get_remaining_games_bulk(
            [p.team for p in (*rostered, *candidates)], week.start, week.end
        )
    builder = PlayerContextBuilder(feeds.form, feeds.games, weights)
    projections = index_for(feeds.sleeper, start, end)

    def lines(players: Sequence[Player]) -> dict[str, str]:
        return builder.build_player_lines(
            players,
            start,
            end,
            remaining_games=remaining,
            projections=projections,
            returns=returns,
            splits=splits,
            readings=readings,
        )

    candidate_lines = lines(candidates)
    fits = {
        p.player_key: actions.fit(r, rostered, readings, weights is not None, untouchable)
        for p in candidates
        if (r := readings.get(p.player_key))
    }
    return prompt.wire(
        week=week,
        weights=weights,
        roster=lines(rostered),
        candidates={p.player_key: candidate_lines[p.name] for p in candidates},
        names={p.player_key: p.name for p in candidates},
        fits=fits,
        constraints="\n".join(
            [
                prompt.transactions(team.adds_used, limit),
                *(
                    f"- {n}"
                    for n in untouchables.note(frozenset(p.name for p in rostered if p.player_key in untouchable))
                ),
            ]
        ),
    )
