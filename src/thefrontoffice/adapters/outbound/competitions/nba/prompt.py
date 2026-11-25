"""What the model reads about a basketball week: the prompts and every block in them.

The provider gathers; this renders. Nothing here fetches.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import span
from thefrontoffice.adapters.outbound.competitions.nba.model import WeekMatchup
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES, COUNTED, fantasy_points
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.tasks import task_lines
from thefrontoffice.domain.models import Action, CompetitionContext, task_id

OPPONENT_KEY_PLAYERS = 12
"""Enough of the other roster to name its threats without listing its bench."""

NBA_SCOUT_PROMPT = """
You are an elite NBA Fantasy General Manager and data analyst.
Your goal is to provide a concise, high-impact "Scout Report" for a fantasy basketball league.

LEAGUE RULES:
{league_rules}

CURRENT ROSTER (with Real-World Stats):
- NOTE: Players marked with "[IN IL SPOT]" are currently in Injured Reserve slots and DO NOT take up an active roster spot. You can recommend dropping them ONLY if the replacement player is also injured and can be placed in that IL spot.
{roster_str}

MATCHUP CONTEXT:
{matchup_context}

{schedule_context}

{trans_context}

TO DO — WHAT LEAGUE STATE ALREADY SAYS NEEDS DECIDING:
- Computed from the league, not estimated: IL moves, bench players to start, and pickups each with its drop.
- "WEEK" on a player line, and "Week" in an item, is his worth this week: a game's value ({value_unit}),
  blending his recent run with Sleeper's projection, nudged up to a tenth by how steady his minutes are,
  times the games he can play before the week ends. Items need a fifth more worth than the player replaced.
- "SLUMP" or "HOT" on a player line: his value a game over his last 5 ran well under or over Sleeper's
  projection, on average and in most of the games, with the categories it shows in; his value is then weighed
  three-quarters on those games. "RETURN UNCLEAR": out several straight with no firm return, so no games counted.
  A to-do's "Trade talk" is a story naming him in trade talk: his role may not last.
- Yahoo lineups are set daily: a start item is for today, a bench player with a game tonight over a starter without one or clearly weaker a game.
- The manager sees this list; your verdicts appear beside it, so judge these items rather than restating them.
{tasks_str}

TOP FREE AGENTS {free_agent_basis}:
{fas_str}

- NOTE: "Without <teammate> (status)" is that player's per-game line in the games a regular teammate missed,
  against the games they played together. Where the teammate is out, the without-line is what the player is
  worth now; "With <teammate>" means the teammate is due back, and the with-line is what he is worth.

YOUR TASK:
1. {analysis}
2. Compare the underperformers on the current roster with the high-upside players on the waiver wire using the provided stats.
3. {recommendation_instructions}
4. For each recommendation, provide:
    - **Reasoning**: {reasoning} Factor in remaining games — players with MORE games left in the matchup period offer more stat production potential.
    - **Drop Target**: Suggest a specific player from the current roster to drop, with a clear justification (e.g., redundant stats, poor recent form, fewer games remaining, or non-active status).
5. Give a verdict on every TO DO item, by its id: AGREE to make it, OVERRULE when news, role or schedule
   says otherwise, WAIT when it turns on news due before the next game. Never repeat a TO DO item as a move.
6. Use a professional, tactical tone. Avoid flowery prose.

Return your analysis in the required structured form. Guidance for the fields:
- situation: {situation}
- focus: {focus}
- verdicts: exactly one per TO DO item, `task` set to its id ('{first_task}'). Empty if the list is empty.
- moves: exactly three, most valuable first. Put the games the player has left in `metric`,
  from the schedule data above (e.g. "{metric_example}"). Use action ADD when adds remain,
  paired with the player it `replaces`; MONITOR when they do not, with `replaces` left empty.
- Keep every field tactical and specific. No filler, no restating the inputs.
"""

NBA_TRADE_PROMPT = """
# 🎭 Trade Evaluation Request

## 1. The Trade
**Giving Away:**
{giving_str}

**Receiving:**
{receiving_str}

## 2. Team Context
{matchup_context}

## 3. Current Roster
{roster_str}

## 4. Analysis Instructions
Act as a ruthless specific NBA Fantasy General Manager. Analyze this trade for my team.
compare the two sides based on:
1. **Statistical Impact**: {impact}
2. **Schedule Advantage**: Who has more games in the playoff weeks?
3. **Shutdown Risk**: Are any of the players receiving at risk of being shut down by tanking teams? Warning if so.
4. **Roster Awareness**: DO NOT recommend acquiring players that are already on my Current Roster.
5. **Verdict**: Should I accept, reject, or counter?

Return the evaluation in the required structured form. Field guidance:
- gains / losses: short labels in this league's own currency ({currency}).
- impact: the net change, referencing recent form.
- schedule: how the remaining games compare, especially through the fantasy playoff weeks.
- risk: availability risk on the incoming side — shutdowns on tanking teams, injury designations.
- strategy: what to do next, including any counter worth offering.
"""

NBA_WIRE_PROMPT = """
You are an elite NBA fantasy basketball manager deciding which available players are worth a roster spot.

LEAGUE RULES:
{league_rules}
- A claim costs a roster spot and one of the week's adds, so every ADD names who on the roster makes way.

READING THE PLAYER LINES:
- [NG left] is how many games the player's TEAM has left this matchup period; PROJ is Sleeper's projection.
- "WEEK" is his worth this week: a game's value ({value_unit}), blending his recent run with the
  projection, nudged up to a tenth by how steady his minutes are, times the games he can play.
- "back ~date" is when ESPN expects an injured player back.
- "Without <teammate> (status)" is his per-game line in the games a regular teammate missed; where the teammate
  is out, that line is what he is worth now. "With <teammate>" means the teammate is due back.
- "fits" names the weakest player on your roster he beats by a fifth this week, and by how much.

{situation}

{constraints}

YOUR ROSTER (who could make way):
{roster_str}

THE AVAILABLE PLAYERS TO JUDGE, each with its id:
{candidates_str}

YOUR TASK:
Give exactly one call per available player above, by id. ADD to claim him now, naming in `drop` who on the
roster makes way — only while adds remain. WATCH when a change in his situation — a teammate's injury, a
return, minutes trending up — would make him worth it, or when no adds remain. PASS otherwise. Ground each
reason in role, minutes, schedule or news, not the numbers alone.

Return the calls in the required structured form.
"""

NO_MATCHUP = "No head-to-head matchup this week."


@dataclass(frozen=True)
class Scoring:
    """How a league is won, in each place the prompts have to say it."""

    rules: str
    free_agent_basis: str
    analysis: str
    reasoning: str
    situation: str
    focus: str
    metric_example: str
    impact: str
    currency: str
    value_unit: str


CATEGORY_LEAGUE = Scoring(
    rules=(
        f"- This is a Category League ({', '.join(c.label for c in CATEGORIES)}).\n"
        "- Victory is determined by winning the majority of categories (e.g., 5-4 in a 9-cat league).\n"
        '- STRATEGY: Prioritize categories that are "CLOSE" (either winning or losing by a small margin).\n'
        "- DO NOT chase categories that are lost by a landslide.\n"
        "- Focus on securing a 5-4 or 6-3 win; the exact score doesn't matter as much as the win."
    ),
    free_agent_basis="BY CATEGORY (Last 7 Days)",
    analysis=(
        'Analyze the matchup: Identify "Close" categories where a small boost could flip the category '
        'in our favor or secure a slim lead. Use specific category names (e.g., "trailing in BLK by 5").'
    ),
    reasoning='Why this player helps specifically in the "Close" categories identified.',
    situation=(
        'name specific categories and margins (e.g. "trailing in BLK by 5"), and say\n'
        "  which are worth contesting. Ignore categories lost by a landslide."
    ),
    focus="only the categories genuinely in play, e.g. ['BLK', 'FG%'].",
    metric_example="4 games left, 2.1 blk",
    impact="Net change in categories (L15/L30 days).",
    currency="categories here, e.g. ['REB', 'BLK']",
    value_unit=(
        "his contribution across the scored categories, each counted in its spread across the players read, "
        "turnovers against"
    ),
)


def points_league(weights: Mapping[str, float]) -> Scoring:
    """How a points league is won, under its own weights."""
    return Scoring(
        rules=(
            f"- This is a Points League: every stat scores its weight ({weighting(weights)}).\n"
            "- Victory is determined by the higher fantasy-point total for the week. "
            "Categories win nothing by themselves.\n"
            '- A line ending "= N fpts" gives fantasy points under these weights: per game in a recent '
            "window, the period's total after PROJ.\n"
            "- STRATEGY: maximize fantasy points over the games left — games times points per game. "
            "A deficit the projection cannot close needs more games, not a specialist."
        ),
        free_agent_basis="BY FANTASY POINTS PER GAME (Last 15 Games, or every game while fewer)",
        analysis=(
            "Analyze the matchup: the fantasy-point margin now and as projected, and how many points "
            'the games left could still swing (e.g., "trailing by 226, projected to lose by 211").'
        ),
        reasoning="How many fantasy points this player adds over the games left, against the player dropped.",
        situation=(
            'the fantasy-point margin, scored and projected (e.g. "trailing by 226, projected\n'
            '  to lose by 211"), and whether the games left can close it.'
        ),
        focus="what wins the points, e.g. ['games left', 'BLK at 3 pts'].",
        metric_example="4 games left, 38.5 fpts/g",
        impact="Net change in fantasy points per game (L15/L30 days).",
        currency="fantasy points per game here, e.g. ['+6.5 fpts/g']",
        value_unit="fantasy points under the league's weights",
    )


def scoring(weights: Mapping[str, float] | None) -> Scoring:
    """A points league's wording where the league has weights; a category league's otherwise."""
    return points_league(weights) if weights else CATEGORY_LEAGUE


def _stat_label(stat: str) -> str:
    """A Yahoo stat id by the label a line tags it with, where this app counts it."""
    return COUNTED[stat].label if stat in COUNTED else f"stat {stat}"


def weighting(weights: Mapping[str, float]) -> str:
    """'PTS 1, REB 1.2, TO -1': each weighted stat and what one of it scores."""
    return ", ".join(f"{_stat_label(stat)} {weight:g}" for stat, weight in weights.items())


def categories(line: Mapping[str, float]) -> str:
    """A nine-category line in prompt shape: '25.3p 10.1r ... FG48.2% FT80.0% 2.1to'."""
    return " ".join(c.tagged(line[c.label]) for c in CATEGORIES if c.label in line)


def scored(line: Mapping[str, float], weights: Mapping[str, float] | None) -> str:
    """A line in prompt shape, closed by its fantasy points where the league scores them."""
    points = fantasy_points(line, weights) if weights else None
    return categories(line) + (f" = {points:.1f} fpts" if points is not None else "")


def matchup(week: WeekMatchup | None, weights: Mapping[str, float] | None = None) -> str:
    """The head-to-head as the model reads it: the score, each stat side by side, their threats.

    In a points league the score is fantasy points, beside Yahoo's projected
    final, and the stats listed are the ones the league weights, each with its weight.
    """
    if week is None:
        return NO_MATCHUP
    mine, theirs = week.mine.stats, week.opponent.stats
    threats = ", ".join(f"{p.name} ({p.position})" for p in week.opponent_roster[:OPPONENT_KEY_PLAYERS])
    opponent = f"\nCURRENT MATCHUP: Playing against {week.opponent.name}"
    if weights:
        breakdown = "".join(
            f"\n- {_stat_label(stat)}: {mine.get(stat, 'N/A')} vs {theirs.get(stat, 'N/A')} (x{weight:g})"
            for stat, weight in weights.items()
        )
        projected = (
            f"\nPROJECTED FINAL (Yahoo): You {week.mine.projected} - {week.opponent.projected} Opponent"
            if week.mine.projected and week.opponent.projected
            else ""
        )
        return (
            f"{opponent}\nMATCHUP SCORE (fantasy points): You {week.mine.points} - {week.opponent.points} Opponent"
            f"{projected}\nSTAT TOTALS BEHIND THE POINTS (Us vs Opponent, weight):{breakdown}"
            f"\nOPPONENT KEY PLAYERS: {threats}"
        )
    breakdown = "".join(
        f"\n- {c.label}: {mine.get(c.yahoo_stat, 'N/A')} vs {theirs.get(c.yahoo_stat, 'N/A')}" for c in CATEGORIES
    )
    return (
        f"{opponent}\nMATCHUP SCORE: You {week.mine.points} - {week.opponent.points} Opponent"
        f"\nCATEGORY BREAKDOWN (Us vs Opponent):{breakdown}"
        f"\nOPPONENT KEY PLAYERS: {threats}"
    )


def transactions(used: int, limit: int) -> str:
    """The week's add budget, and how it should bend the advice."""
    return (
        f"TRANSACTION CONTEXT:\n- Adds Used: {used}/{limit}\n"
        f"- Remaining Adds: {max(0, limit - used)}\n"
        "- NOTE: Prioritize aggressive streaming if adds are high, "
        "or conservative quality pickups if adds are low."
    )


def recommendation(adds_left: int) -> str:
    """Adds to make while the budget lasts; players to watch once it is spent."""
    if adds_left > 0:
        return "Recommend **3 players** to add from the Free Agents list."
    return (
        "You have **0 adds remaining**. You CANNOT add players. Instead, identify "
        "**3 players to MONITOR** for next week who fit the team's needs."
    )


def schedule(
    week: WeekMatchup | None, remaining_games: Mapping[str, int], projected: bool, unscheduled: Sequence[date] = ()
) -> str:
    """Whether projections stand behind the lines, then each club's games left in the period.

    Where the NBA has days of the period still to schedule (`week.unsettled`), says the counts are a floor.
    """
    note = (
        "PROJECTIONS: lines marked PROJ carry projected totals for this matchup period — "
        "games, then the categories. Prefer them to recent form when the two disagree, "
        "since they already account for the schedule and expected minutes.\n"
        "- The bracketed [NG left] is how many games the player's TEAM has left. The PROJ "
        "game count is how many that PLAYER is expected to play. A player whose PROJ count "
        "is lower than his team's is expected to miss games — treat the gap as a warning, "
        "not a contradiction.\n"
        if projected
        else "PROJECTIONS: unavailable for this period. Reason from recent form and games "
        "remaining, and say so rather than implying a forecast.\n"
    )
    if week is None or not remaining_games:
        return note
    rows = "".join(
        f"- {team}: {count} games left\n"
        for team, count in sorted(remaining_games.items(), key=lambda item: item[1], reverse=True)
    )
    pending = (
        f"SCHEDULE NOT FINAL: the NBA has yet to schedule games {span(unscheduled[0], unscheduled[-1])} "
        "(NBA Cup knockouts), so every count below is a floor, not the week's total.\n"
        if unscheduled
        else ""
    )
    return f"{note}MATCHUP PERIOD: {week.start} to {week.end}\n{pending}REMAINING GAMES BY TEAM:\n{rows}"


def scout(
    *,
    roster: str,
    week: WeekMatchup | None,
    free_agents: str,
    schedule_context: str,
    trans_context: str,
    adds_left: int,
    weights: Mapping[str, float] | None = None,
    tasks: Sequence[Action] = (),
    team_news: str = "",
) -> str:
    """The scout's prompt, worded for how the league is won: `weights` for a points league, None for categories.

    `tasks` is the week's to-do list as the page shows it, numbered here so a verdict can name its item.
    `team_news` is each club's stories once (`news.team_block`), after the matchup.
    """
    league = scoring(weights)
    return NBA_SCOUT_PROMPT.format(
        league_rules=league.rules,
        roster_str=roster,
        matchup_context=matchup(week, weights) + team_news,
        free_agent_basis=league.free_agent_basis,
        fas_str=free_agents,
        schedule_context=schedule_context,
        trans_context=trans_context,
        analysis=league.analysis,
        recommendation_instructions=recommendation(adds_left),
        reasoning=league.reasoning,
        situation=league.situation,
        focus=league.focus,
        metric_example=league.metric_example,
        value_unit=league.value_unit,
        tasks_str=task_lines(tasks) or "- Nothing: the league state asks for no move this week.\n",
        first_task=task_id(1),
    )


def week_line(reading: Reading) -> str:
    """' | WEEK: 3G × 41.5/g × 1.1 (minutes) = 137.0': his worth this week, and what it is made of — then his
    streak (`worth.streak`) and a return in doubt (`Reading.missed`), where either is his."""
    worth = reading.worth
    if worth is None or reading.per_game is None:
        return ""
    nudge = f" × {reading.usage:g} (minutes)" if reading.usage != 1 else ""
    found = reading.streak
    streak = f" | {found.label.upper()}: {found.short()}" if found is not None else ""
    doubt = f" | RETURN UNCLEAR: out {reading.missed} straight" if reading.missed else ""
    return f" | WEEK: {reading.games}G × {reading.per_game:.1f}/g{nudge} = {worth:.1f}{streak}{doubt}"


def trade(
    *,
    giving: str,
    receiving: str,
    week: WeekMatchup | None,
    roster: str,
    weights: Mapping[str, float] | None = None,
    team_news: str = "",
) -> str:
    """The trade prompt, in the league's currency: `weights` for a points league, None for categories.

    `team_news` is each club's stories once (`news.team_block`), after the matchup.
    """
    league = scoring(weights)
    return NBA_TRADE_PROMPT.format(
        giving_str=giving,
        receiving_str=receiving,
        matchup_context=matchup(week, weights) + team_news,
        roster_str=roster,
        impact=league.impact,
        currency=league.currency,
    )


def wire(
    *,
    week: WeekMatchup | None,
    weights: Mapping[str, float] | None,
    roster: Mapping[str, str],
    candidates: Mapping[str, str],
    names: Mapping[str, str],
    fits: Mapping[str, str],
    constraints: str,
    team_news: str = "",
) -> CompetitionContext:
    """The prompt asking for one call per candidate, each by the id the call has to name.

    `candidates` is each one's player line by Yahoo's key, `names` his name, and
    `fits` the drop he streams over, where he does (`actions.fit`). A candidate's
    target is his line alone, so a call on him is kept against it whatever else is asked. `team_news` is each
    club's stories once (`news.team_block`), in the situation.
    """
    league = scoring(weights)
    targets = {
        pid: f"- [id {pid}] {line.removeprefix('- ')}" + (f"  fits: {fit}\n" if (fit := fits.get(pid)) else "")
        for pid, line in candidates.items()
    }
    situation = matchup(week, weights) + team_news
    text = NBA_WIRE_PROMPT.format(
        league_rules=league.rules,
        value_unit=league.value_unit,
        situation=situation,
        constraints=constraints,
        roster_str="".join(roster.values()),
        candidates_str="".join(targets.values()),
    )
    return CompetitionContext(
        prompt=text,
        situation=situation,
        constraints=constraints,
        roster_lines=dict(roster),
        candidate_lines={names[pid]: line for pid, line in targets.items()},
        targets=targets,
    )
