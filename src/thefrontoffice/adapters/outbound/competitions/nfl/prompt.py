"""Rendering a football week as the text a model reads.

Kept away from the provider because it is a different kind of work: everything
here turns state already gathered into prose, and none of it decides anything.
The provider fetches and the prompt describes.
"""

from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Evidence, season_average
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection, Trending
from thefrontoffice.adapters.outbound.competitions.nfl.news import PlayerNews, dated
from thefrontoffice.adapters.outbound.competitions.nfl.rules import STREAMED, listed, scoring_label
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.domain.models import Action, CompetitionContext, Stat, task_id

AVAILABLE_PLAYER_LIMIT = 25
TRENDING_LIMIT = 10
TRENDING_HOURS = 24
"""How far back the crowd's adds are counted."""

# How every NFL prompt's player lines read. Shared, because the lines are
# built by one function for every prompt, and two explanations of one format
# would drift apart.
NFL_READING_PLAYER_LINES = """READING THE PLAYER LINES:
- Under a player, where games have been played, is what the projection rests on. The matchup:
  how many points a game this week's opponent has given up to the position, ranked 1 (the most,
  the softest) to 32. The role, over his last games: share of the offense's snaps, carries,
  targets and share of the team's targets, and points.
- Weigh role and matchup over the projection itself. A projection is a single number that hides
  why; a rising target share or a soft defense is the why.
- Never recommend a DROP off one poor game, or of a player whose role grows while a teammate
  ahead of him is out. A drop is the least reversible move, so it needs the strongest case.
- A bye or a one-week absence is never a reason to DROP: he scores nothing on your bench that week
  either way. Weigh a drop by his points a game this season, and suggest an ADD only when the player
  starts this week or is worth more a game than the one he replaces. Kickers and defenses are the
  exception: they are streamed for the week's matchup.
- A "news" line under a player is a recent headline about him, dated, from his own club's feed.
- A player marked [reserve slot] is in an injured-reserve or taxi slot: he cannot start this week
  without a move first, and costs no roster spot while he is there."""


NFL_SCOUT_PROMPT = (
    """
You are an elite NFL fantasy football manager.
Produce a concise, high-impact weekly report.

LEAGUE RULES:
- Scoring: {scoring_label}. Every projection below is in that currency.
- Each player plays at most one game per week, so a bye or an inactive is a zero, not a reduced score.
- Winning means out-scoring one opponent this week. Chasing season-long upside at the cost of this
  week's points is only correct when the roster is already comfortably ahead.

"""
    + NFL_READING_PLAYER_LINES
    + """

{situation}

{constraints}

YOUR CURRENT LINEUP (slot, player, projection):
{lineup_str}

BENCH:
{bench_str}

TO DO — WHAT LEAGUE STATE ALREADY SAYS NEEDS DECIDING:
- Computed exactly from the league, not estimated: starters who cannot play, empty slots, swaps
  the bench allows, byes ahead, the trade deadline. The manager sees this list; your verdicts
  appear beside it, so judge these items rather than restating them.
{tasks_str}

TOP AVAILABLE PLAYERS (not rostered anywhere in this league):
{available_str}

TRENDING ADDS ACROSS SLEEPER (crowd signal, often ahead of projections):
{trending_str}

YOUR TASK:
1. Read the matchup: are we favored or chasing, and by how much?
2. Give a verdict on every TO DO item, by its id. AGREE to make it; OVERRULE when the role, the
   matchup or the news says otherwise, even where the projection favors it; WAIT when it turns on
   news due before its deadline, such as a questionable player's final status.
3. Recommend further moves only where the TO DO list misses one — chiefly ADDs from the available
   list, each paired with a DROP from the bench. Never repeat a TO DO item as a move.
4. Skip any move you would not actually make. Three good moves beat six padded ones.

Return your analysis in the required structured form. Field guidance:
- situation: the matchup, the projected margin, and what it turns on.
- focus: what this week hinges on — thin positions, byes, injury risk. Short labels.
- verdicts: exactly one per TO DO item, `task` set to its id ('{first_task}'). Empty if the list is empty.
- moves: action START/BENCH/ADD/MONITOR. Put the projected points in `metric`
  (e.g. "14.2 proj pts, +4.1 over Smith"). Pair every ADD with the player it `replaces`.
- Be specific and tactical. Do not restate the inputs.
"""
)


NFL_TRADE_PROMPT = """
# Trade Evaluation Request

## 1. The Trade
**Giving Away:**
{giving_str}

**Receiving:**
{receiving_str}

## 2. Team Context
{situation}

{constraints}

## 3. Current Roster
{roster_str}

## 4. Analysis Instructions
Act as a ruthless NFL fantasy general manager. Scoring is {scoring_label}, and every
projection above is in that currency. Judge this trade on:
1. **Starting-lineup impact**: only points that reach the starting lineup count. Upgrading a
   bench player behind an entrenched starter is worth little.
2. **Positional scarcity**: a mid-range RB is not interchangeable with a mid-range WR when the
   lineup slots differ, and depth at a position you already start two of is worth less.
3. **Byes and availability**: a bye week or an injury designation is a zero, not a reduced
   score. Check whether the incoming side leaves a hole in a given week.
4. **Rest of season**: weigh the remaining schedule, especially the fantasy playoff weeks.
5. **Role over projection**: where a player line carries snap share, targets and carries, judge
   him on that usage. A projection hides whether a role is growing or shrinking.
6. **Roster awareness**: do not recommend acquiring a player already on this roster.

Return the evaluation in the required structured form. Field guidance:
- gains / losses: short labels in this league's own terms, e.g. ['RB depth', 'WR ceiling'].
- impact: the net weekly change to the starting lineup, in points.
- schedule: bye weeks and the playoff-week fixtures on both sides.
- risk: availability risk on the incoming side — injury designations, committee usage.
- strategy: what to do next, including any counter worth offering.
"""


NFL_WIRE_PROMPT = (
    """
You are an elite NFL fantasy football manager deciding which available players are worth a roster spot.

LEAGUE RULES:
- Scoring: {scoring_label}. Every projection below is in that currency.
- A claim costs a roster spot, so every ADD names who on the roster makes way.

"""
    + NFL_READING_PLAYER_LINES
    + """
- "Fits" compares an available player with the weakest starter he could replace: the gap in
  projected points this week, positive where he would start.

{situation}

{constraints}

YOUR ROSTER (who could make way):
{roster_str}

THE AVAILABLE PLAYERS TO JUDGE, each with its id:
{candidates_str}

YOUR TASK:
Give exactly one call per available player above, by id. ADD to claim him now, naming in `drop`
who on the roster makes way. WATCH when a change in his situation — a teammate's injury, a role
trending up — would make him worth it. PASS otherwise. Ground each reason in role, matchup or
news, not the projection alone.

Return the calls in the required structured form.
"""
)


def build(state: Week, tasks: list[Action], trending: Sequence[Trending] | None) -> CompetitionContext:
    """The scouting prompt, and the parts it was assembled from.

    `tasks` is the week's to-do list as the page shows it, numbered here so
    each verdict the model returns can be put back beside its row. `trending`
    is None where the crowd's adds would not load.
    """
    evidence, news = state.evidence, state.news
    lineup_str = "".join(
        f"- {slot.slot}: {slot.player.name} ({slot.player.position}, {slot.player.team}) "
        f"{slot.player.points:.2f} pts vs {slot.player.opponent or 'TBD'}\n"
        + (f"  {behind}\n" if (behind := evidence.describe(slot.player)) else "")
        + news_lines(news, slot.player.player_id)
        if slot.player
        else f"- {slot.slot}: (empty)\n"
        for slot in state.lineup
    )
    bench_str = "".join(held_line(p, state) for p in state.sitting) or "- (none)\n"
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
        f"Current lineup projects {current_points:.2f} points.",
        f"The best legal lineup projects {best_points:.2f}"
        + (f", so {on_bench:.2f} points are sitting on the bench." if on_bench > 0 else "."),
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
        first_task=task_id(1),
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
        worth=_worth(state),
    )


def _worth(state: Week) -> dict[str, float]:
    """Each player who could be added or dropped, by his average a game this season.

    Yours — including a player on bye, who has no projection this week and
    is exactly the one a model reading projections would cut — and everyone
    nobody holds: whoever the model could name in a move. Kickers and
    defenses are left out — they are streamed for the week's matchup, so a
    season average is the wrong measure of either.
    """
    free = [p for pid, p in state.projections.items() if pid not in state.owned]
    return {p.name: season_average(state.evidence, p) for p in (*state.projected, *free) if p.position not in STREAMED}


def trade(state: Week, giving: Sequence[Projection], receiving: Sequence[Projection]) -> CompetitionContext:
    """The trade prompt: both sides priced against this roster, on the week every other view reads."""
    roster = roster_lines(state)
    situation, _ = matchup(state)
    constraints = lineup_slots(
        state,
        "Only points from the starting lineup score. Bench depth has value only as insurance or as a future starter.",
    )
    text = NFL_TRADE_PROMPT.format(
        giving_str="".join(player_line(p, state.evidence, state.news) for p in giving),
        receiving_str="".join(player_line(p, state.evidence, state.news) for p in receiving),
        situation=situation,
        constraints=constraints,
        roster_str="".join(roster.values()),
        scoring_label=scoring_label(state.league.scoring_format),
    )
    return CompetitionContext(prompt=text, situation=situation, constraints=constraints, roster_lines=roster)


def wire(state: Week, candidates: Mapping[str, Projection], fits: Mapping[str, str]) -> CompetitionContext:
    """The prompt asking for one call per candidate, each by the id the call has to name.

    `candidates` is keyed by player id; `fits` holds how each would fit this
    lineup, where he would.
    """
    targets = {pid: _wire_line(p, state, fits.get(pid, "")) for pid, p in candidates.items()}
    candidate_lines = {p.name: targets[pid] for pid, p in candidates.items()}
    roster = roster_lines(state)
    situation, _ = matchup(state)
    constraints = lineup_slots(state, "Only the starting lineup scores; a bench spot is insurance or a future starter.")
    text = NFL_WIRE_PROMPT.format(
        scoring_label=scoring_label(state.league.scoring_format),
        situation=situation,
        constraints=constraints,
        roster_str="".join(roster.values()),
        candidates_str="".join(candidate_lines.values()),
    )
    return CompetitionContext(
        prompt=text,
        situation=situation,
        constraints=constraints,
        roster_lines=roster,
        candidate_lines=candidate_lines,
        targets=targets,
    )


def _wire_line(player: Projection, state: Week, fit: str) -> str:
    """One candidate as the model reads him: his id, his line, and how he fits."""
    line = player_line(player, state.evidence, state.news, bullet=f"- [id {player.player_id}] ")
    return line + (f"  fits: {fit}\n" if fit else "")


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
            label="Lineup", value=f"{state.current_points:.2f} proj · best {state.best_points:.2f}", tone="warning"
        )
    else:
        lineup = Stat(label="Lineup", value=f"{state.current_points:.2f} proj")
    return [lineup, *matchup(state)[1]]


def lineup_slots(state: Week, *notes: str) -> str:
    """The lineup a model is reasoning about, and what it should keep in mind about it."""
    return f"LINEUP SLOTS: {', '.join(state.league.starting_slots)}\n" + "\n".join(f"- {note}" for note in notes)


def roster_lines(state: Week) -> dict[str, str]:
    """Your roster as the model reads it, best projected first, keyed by name."""
    return {p.name: held_line(p, state) for p in sorted(state.projected, key=lambda x: -x.points)}


RESERVE_MARK = " [reserve slot]"
"""How the model is told a player cannot start where he sits: `NFL_READING_PLAYER_LINES` explains it."""


def held_line(p: Projection, state: Week) -> str:
    """One of your own players as the model reads him, marked where a reserve or taxi slot keeps him out of the lineup."""
    mark = RESERVE_MARK if p.player_id in state.roster.reserve_ids else ""
    return player_line(p, state.evidence, state.news, mark=mark)


NEWS_PER_PLAYER = 2
"""Enough to show a trend in the coverage, few enough that the pool stays readable."""


def player_line(p: Projection, evidence: Evidence, news: PlayerNews, bullet: str = "- ", mark: str = "") -> str:
    """One player as the model reads him: the projection, then what it rests on."""
    injury = f" [{p.injury_status}]" if listed(p.injury_status) else ""
    opponent = f" vs {p.opponent}" if p.opponent else " (no game)"
    behind = evidence.describe(p)
    return (
        f"{bullet}{p.name} ({p.position}, {p.team}){injury}{mark}{opponent}: {p.points:.2f} proj pts\n"
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
        name = meta.name if meta else None
        if not name:
            continue
        proj = state.projections.get(item.player_id)
        points = f"{proj.points:.2f} proj pts" if proj else "no projection"
        lines.append(f"- {name}: added by {item.count:,} managers in {TRENDING_HOURS}h, {points}\n")
    return "".join(lines) or "- (none)\n"


def matchup(state: Week) -> tuple[str, list[Stat]]:
    """The matchup as prose for the prompt, and as figures for the header."""
    roster = state.roster
    header = (
        f"LEAGUE: {state.league.name} ({state.league.total_rosters} teams)\n"
        f"WEEK: {state.week}\nYOUR RECORD: {roster.record}, {roster.points_for:.2f} points for\n"
    )
    if state.matchup is None:
        return header + "No head-to-head matchup this week.\n", []

    mine, theirs = state.matchup
    opponent = state.opponent
    name = (state.team_name(opponent) + f" ({opponent.record})") if opponent else "Opponent"
    margin = round(mine.points - theirs.points, 2)

    prose = header + f"OPPONENT: {name}\nLIVE SCORE: you {mine.points:.2f} - {theirs.points:.2f} them\n"
    stats = [
        Stat(label="Opponent", value=name),
        # Toned by who is ahead: the score is the verdict so far. No separate
        # margin beside it — that is the same two numbers subtracted, and
        # read next to the simulated "Likely margin" it looked like a second
        # forecast that disagreed with the first.
        Stat(
            label="Live",
            value=f"{mine.points:.2f} – {theirs.points:.2f}",
            tone="good" if margin > 0 else "warning" if margin < 0 else "neutral",
        ),
    ]
    return prose, stats
