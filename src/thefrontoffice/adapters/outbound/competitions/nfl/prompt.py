"""Rendering a football week as the text a model reads.

Kept away from the provider because it is a different kind of work: everything
here turns state already gathered into prose, and none of it decides anything.
The provider fetches and the prompt describes.
"""

from collections.abc import Sequence

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection, Trending
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews, dated
from thefrontoffice.adapters.outbound.competitions.nfl.rules import listed, scoring_label
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.config.constants import NFL_SCOUT_PROMPT
from thefrontoffice.domain.models import Action, CompetitionContext, Stat, task_id

AVAILABLE_PLAYER_LIMIT = 25
TRENDING_LIMIT = 10
TRENDING_HOURS = 24
"""How far back the crowd's adds are counted."""


def build(state: Week, tasks: list[Action], trending: Sequence[Trending] | None) -> CompetitionContext:
    """The scouting prompt, and the parts it was assembled from.

    `tasks` is the week's to-do list as the page shows it, numbered here so
    each verdict the model returns can be put back beside its row. `trending`
    is None where the crowd's adds would not load.
    """
    evidence, news = state.evidence, state.news
    lineup_str = "".join(
        f"- {slot.slot}: {slot.player.name} ({slot.player.position}, {slot.player.team}) "
        f"{slot.player.points:.1f} pts vs {slot.player.opponent or 'TBD'}\n"
        + (f"  {behind}\n" if (behind := evidence.describe(slot.player)) else "")
        + news_lines(news, slot.player.player_id)
        if slot.player
        else f"- {slot.slot}: (empty)\n"
        for slot in state.lineup
    )
    bench_str = (
        "".join(player_line(p, evidence, news) for p in state.projected if p.player_id not in state.starter_ids)
        or "- (none)\n"
    )
    tasks_str = "".join(task_line(i, task) for i, task in enumerate(tasks, start=1)) or (
        "- None. Nothing in league state needs deciding: the lineup is the best legal one and nobody "
        "in it is ruled out.\n"
    )

    available = _available_players(state)
    available_lines = {p.name: player_line(p, evidence, news) for p in available}

    situation, _ = matchup(state)
    current_points, best_points, on_bench = state.current_points, state.best_points, state.on_bench
    constraints = lineup_slots(
        state,
        f"Current lineup projects {current_points:.1f} points.",
        f"The best legal lineup projects {best_points:.1f}"
        + (f", so {on_bench:.1f} points are sitting on the bench." if on_bench > 0 else "."),
        "Bench players score nothing. A start/sit change costs nothing; an add costs a roster spot.",
    )

    prompt = NFL_SCOUT_PROMPT.format(
        scoring_label=scoring_label(state.league.scoring_format),
        situation=situation,
        constraints=constraints,
        lineup_str=lineup_str or "- (no lineup set)\n",
        bench_str=bench_str,
        tasks_str=tasks_str,
        available_str="".join(available_lines.values()) or "- (none available)\n",
        trending_str=_trending(state, trending),
    )

    return CompetitionContext(
        prompt=prompt,
        situation=situation,
        constraints=constraints,
        extra=f"TO DO:\n{tasks_str}",
        roster_lines=roster_lines(state),
        candidate_lines=available_lines,
        headline=headline(state),
        tasks=tasks,
    )


def task_line(position: int, task: Action) -> str:
    """One to-do item as the model reads it: its id, the move, why, and what it rests on."""
    when = f" ({task.when})" if task.when else ""
    evidence = "".join(f"    {line.label}: {line.value}\n" for line in task.evidence)
    return f"- {task_id(position)} [{task.urgency}, {task.kind}] {task.title}{when}. {task.reason}\n{evidence}"


def headline(state: Week) -> list[Stat]:
    """Where this team stands this week, in points: the lineup, what the bench still holds, and the matchup.

    The season's own figures — record, points for — are the league view's,
    and the week is already in the page's title. Only points left on the
    bench warns: it is the one figure here that is a decision still open.
    """
    if state.on_bench > 0:
        lineup = Stat(
            label="Lineup", value=f"{state.current_points:.1f} · best {state.best_points:.1f}", tone="warning"
        )
    else:
        lineup = Stat(label="Lineup", value=f"{state.current_points:.1f}")
    return [lineup, *matchup(state)[1]]


def lineup_slots(state: Week, *notes: str) -> str:
    """The lineup a model is reasoning about, and what it should keep in mind about it."""
    return f"LINEUP SLOTS: {', '.join(state.league.starting_slots)}\n" + "\n".join(f"- {note}" for note in notes)


def roster_lines(state: Week) -> dict[str, str]:
    """Your roster as the model reads it, best projected first, keyed by name."""
    return {
        p.name: player_line(p, state.evidence, state.news) for p in sorted(state.projected, key=lambda x: -x.points)
    }


NEWS_PER_PLAYER = 2
"""Enough to show a trend in the coverage, few enough that the pool stays readable."""


def player_line(p: Projection, evidence: Evidence, news: PlayerNews, bullet: str = "- ") -> str:
    """One player as the model reads him: the projection, then what it rests on."""
    injury = f" [{p.injury_status}]" if listed(p.injury_status) else ""
    opponent = f" vs {p.opponent}" if p.opponent else " (no game)"
    behind = evidence.describe(p)
    return (
        f"{bullet}{p.name} ({p.position}, {p.team}){injury}{opponent}: {p.points:.1f} proj pts\n"
        + (f"  {behind}\n" if behind else "")
        + news_lines(news, p.player_id)
    )


def news_lines(news: PlayerNews, player_id: str) -> str:
    """A player's latest headlines, dated, with ESPN's one-line summary."""
    return "".join(
        f"  news, {dated(a)}: {a.headline}" + (f" — {a.summary}" if a.summary else "") + "\n"
        for a in news.latest(player_id, NEWS_PER_PLAYER)
    )


def _available_players(state: Week) -> Sequence[Projection]:
    """Highest-projecting players not rostered anywhere in the league."""
    free = [p for pid, p in state.projections.items() if pid not in state.owned and p.points > 0]
    return sorted(free, key=lambda p: p.points, reverse=True)[:AVAILABLE_PLAYER_LIMIT]


def _trending(state: Week, trending: Sequence[Trending] | None) -> str:
    if trending is None:
        return "- (unavailable)\n"
    lines = []
    for item in trending:
        meta = state.players.get(item.player_id)
        name = meta.get("name") if meta else None
        if not name:
            continue
        proj = state.projections.get(item.player_id)
        points = f"{proj.points:.1f} proj pts" if proj else "no projection"
        lines.append(f"- {name}: added by {item.count:,} managers in {TRENDING_HOURS}h, {points}\n")
    return "".join(lines) or "- (none)\n"


def matchup(state: Week) -> tuple[str, list[Stat]]:
    """The matchup as prose for the prompt, and as figures for the header."""
    roster = state.roster
    header = (
        f"LEAGUE: {state.league.name} ({state.league.total_rosters} teams)\n"
        f"WEEK: {state.week}\nYOUR RECORD: {roster.record}, {roster.points_for:.1f} points for\n"
    )
    if state.matchup is None:
        return header + "No head-to-head matchup this week.\n", []

    mine, theirs = state.matchup
    opponent = state.opponent
    name = (state.team_name(opponent) + f" ({opponent.record})") if opponent else "Opponent"
    margin = round(mine.points - theirs.points, 1)

    prose = header + f"OPPONENT: {name}\nLIVE SCORE: you {mine.points:.1f} - {theirs.points:.1f} them\n"
    stats = [
        Stat(label="Opponent", value=name),
        # Toned by who is ahead: the score is the verdict so far. No separate
        # margin beside it — that is the same two numbers subtracted, and
        # read next to the simulated "Likely margin" it looked like a second
        # forecast that disagreed with the first.
        Stat(
            label="Live",
            value=f"{mine.points:.1f} – {theirs.points:.1f}",
            tone="good" if margin > 0 else "warning" if margin < 0 else "neutral",
        ),
    ]
    return prose, stats
