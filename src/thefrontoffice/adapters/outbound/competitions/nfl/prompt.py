"""Rendering a football week as the text a model reads.

Kept away from the provider because it is a different kind of work: everything
here turns state already gathered into prose, and none of it decides anything.
The provider fetches and the prompt describes.

`_matchup` returns both the prose and the header figures because they come from
the same three requests; deriving them separately would fetch the scoreboard
twice for one report.
"""

import logging

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews, dated
from thefrontoffice.adapters.outbound.competitions.nfl.week import SCORING_LABELS, Week
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.config.constants import NFL_SCOUT_PROMPT
from thefrontoffice.domain.errors import SleeperAPIError
from thefrontoffice.domain.models import Action, CompetitionContext, Stat, task_id

logger = logging.getLogger(__name__)

AVAILABLE_PLAYER_LIMIT = 25
TRENDING_LIMIT = 10


def build(client: SleeperNFLSource, state: Week, league_id: str, tasks: list[Action]) -> CompetitionContext:
    """The scouting prompt, and the parts it was assembled from.

    `tasks` is the week's to-do list as the page shows it, numbered here so
    each verdict the model returns can be put back beside its row.
    """
    league, roster, week = state.league, state.roster, state.week
    projections, players, projected = state.projections, state.players, state.projected
    lineup = state.lineup

    slots = league.starting_slots
    evidence, news = state.evidence, state.news
    roster_lines = {p.name: player_line(p, evidence, news) for p in sorted(projected, key=lambda x: -x.points)}
    starter_ids = state.starter_ids
    lineup_str = "".join(
        f"- {slot.slot}: {slot.player.name} ({slot.player.position}, {slot.player.team}) "
        f"{slot.player.points:.1f} pts vs {slot.player.opponent or 'TBD'}\n"
        + (f"  {behind}\n" if (behind := evidence.describe(slot.player)) else "")
        + news_lines(news, slot.player.player_id)
        if slot.player
        else f"- {slot.slot}: (empty)\n"
        for slot in lineup
    )
    bench_str = (
        "".join(player_line(p, evidence, news) for p in projected if p.player_id not in starter_ids) or "- (none)\n"
    )
    tasks_str = "".join(task_line(i, task) for i, task in enumerate(tasks, start=1)) or (
        "- None. Nothing in league state needs deciding: the lineup is the best legal one and nobody "
        "in it is ruled out.\n"
    )

    available = _available_players(client, league_id, projections, players)
    available_lines = {p.name: player_line(p, evidence, news) for p in available}
    trending_str = _trending(client, projections, players)

    situation, matchup_stats = matchup(client, league, roster, league_id, week)
    current_points, best_points, on_bench = state.current_points, state.best_points, state.on_bench
    constraints = (
        f"LINEUP SLOTS: {', '.join(slots)}\n"
        f"- Current lineup projects {current_points:.1f} points.\n"
        f"- The best legal lineup projects {best_points:.1f}"
        + (f", so {on_bench:.1f} points are sitting on the bench.\n" if on_bench > 0 else ".\n")
        + "- Bench players score nothing. A start/sit change costs nothing; an add costs a roster spot."
    )

    prompt = NFL_SCOUT_PROMPT.format(
        scoring_label=SCORING_LABELS.get(league.scoring_format, league.scoring_format),
        situation=situation,
        constraints=constraints,
        lineup_str=lineup_str or "- (no lineup set)\n",
        bench_str=bench_str,
        tasks_str=tasks_str,
        available_str="".join(available_lines.values()) or "- (none available)\n",
        trending_str=trending_str,
    )

    return CompetitionContext(
        prompt=prompt,
        situation=situation,
        constraints=constraints,
        extra=f"TO DO:\n{tasks_str}",
        roster_lines=roster_lines,
        candidate_lines=available_lines,
        headline=headline(roster, week, current_points, best_points, on_bench) + matchup_stats,
        tasks=tasks,
    )


def task_line(position: int, task: Action) -> str:
    """One to-do item as the model reads it: its id, the move, why, and what it rests on."""
    when = f" ({task.when})" if task.when else ""
    evidence = "".join(f"    {line.label}: {line.value}\n" for line in task.evidence)
    return f"- {task_id(position)} [{task.urgency}, {task.kind}] {task.title}{when}. {task.reason}\n{evidence}"


def headline(
    roster: SleeperRoster,
    week: int,
    current_points: float,
    best_points: float,
    on_bench: float,
) -> list[Stat]:
    """Where this team stands this week, in points: the lineup, and what the bench still holds.

    The season's own figures — record, points for — are the league view's,
    and the week is already in the page's title. Only points left on the
    bench warns: it is the one figure here that is a decision still open.
    """
    if on_bench > 0:
        return [Stat(label="Lineup", value=f"{current_points:.1f} · best {best_points:.1f}", tone="warning")]
    return [Stat(label="Lineup", value=f"{current_points:.1f}")]


NEWS_PER_PLAYER = 2
"""Enough to show a trend in the coverage, few enough that the pool stays readable."""


def player_line(p: WeeklyProjection, evidence: Evidence | None = None, news: PlayerNews | None = None) -> str:
    """One player as the model reads him: the projection, then what it rests on."""
    injury = f" [{p.injury_status}]" if p.is_questionable else ""
    opponent = f" vs {p.opponent}" if p.opponent else " (no game)"
    behind = evidence.describe(p) if evidence else ""
    return (
        f"- {p.name} ({p.position}, {p.team}){injury}{opponent}: {p.points:.1f} proj pts\n"
        + (f"  {behind}\n" if behind else "")
        + (news_lines(news, p.player_id) if news else "")
    )


def news_lines(news: PlayerNews, player_id: str) -> str:
    """A player's latest headlines, dated, with ESPN's one-line summary."""
    return "".join(
        f"  news, {dated(a)}: {a.headline}" + (f" — {a.summary}" if a.summary else "") + "\n"
        for a in news.latest(player_id, NEWS_PER_PLAYER)
    )


def _available_players(
    client: SleeperNFLSource,
    league_id: str,
    projections: dict[str, WeeklyProjection],
    players: dict[str, PlayerMeta],
) -> list[WeeklyProjection]:
    """Highest-projecting players not rostered anywhere in the league."""
    rostered: set[str] = set()
    for roster in client.get_rosters(league_id):
        rostered.update(roster.player_ids)

    free = [p for pid, p in projections.items() if pid not in rostered and p.points > 0]
    return sorted(free, key=lambda p: p.points, reverse=True)[:AVAILABLE_PLAYER_LIMIT]


def _trending(
    client: SleeperNFLSource, projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
) -> str:
    try:
        trending = client.get_trending("add", limit=TRENDING_LIMIT)
    except SleeperAPIError as e:
        # An independent signal, not load-bearing — losing it degrades the
        # prompt rather than the report.
        logger.warning(f"Skipping trending players: {e}")
        return "- (unavailable)\n"

    lines = []
    for item in trending:
        meta = players.get(item.player_id)
        name = meta.get("name") if meta else None
        if not name:
            continue
        proj = projections.get(item.player_id)
        points = f"{proj.points:.1f} proj pts" if proj else "no projection"
        lines.append(f"- {name}: added by {item.count:,} managers in 24h, {points}\n")
    return "".join(lines) or "- (none)\n"


def matchup(
    client: SleeperNFLSource,
    league: SleeperLeague,
    roster: SleeperRoster,
    league_id: str,
    week: int,
) -> tuple[str, list[Stat]]:
    """The matchup as prose for the prompt, and as figures for the header.

    Built together because they come from the same three requests; deriving
    them separately would fetch the scoreboard twice for one report.
    """
    header = (
        f"LEAGUE: {league.name} ({league.total_rosters} teams)\n"
        f"WEEK: {week}\nYOUR RECORD: {roster.record}, {roster.points_for:.1f} points for\n"
    )
    try:
        matchups = client.get_matchups(league_id, week)
    except SleeperAPIError as e:
        logger.warning(f"No matchup data: {e}")
        return header, []

    mine = next((m for m in matchups if m.get("roster_id") == roster.roster_id), None)
    if not mine or mine.get("matchup_id") is None:
        return header + "No head-to-head matchup this week.\n", []

    opponent = next(
        (
            m
            for m in matchups
            if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster.roster_id
        ),
        None,
    )
    if not opponent:
        return header + "No opponent assigned this week.\n", []

    names = client.get_league_users(league_id)
    by_roster = {r.roster_id: r for r in client.get_rosters(league_id)}
    opp_roster = by_roster.get(int(opponent.get("roster_id", 0)))
    opp_name = names.get(opp_roster.owner_id, "Opponent") if opp_roster else "Opponent"

    mine_points = float(mine.get("points") or 0)
    their_points = float(opponent.get("points") or 0)
    margin = round(mine_points - their_points, 1)

    prose = (
        header
        + f"OPPONENT: {opp_name}"
        + (f" ({opp_roster.record})" if opp_roster else "")
        + f"\nLIVE SCORE: you {mine_points:.1f} - {their_points:.1f} them\n"
    )
    stats = [
        Stat(label="Opponent", value=opp_name + (f" ({opp_roster.record})" if opp_roster else "")),
        # Toned by who is ahead: the score is the verdict so far. No separate
        # margin beside it — that is the same two numbers subtracted, and
        # read next to the simulated "Likely margin" it looked like a second
        # forecast that disagreed with the first.
        Stat(
            label="Live",
            value=f"{mine_points:.1f} – {their_points:.1f}",
            tone="good" if margin > 0 else "warning" if margin < 0 else "neutral",
        ),
    ]
    return prose, stats
