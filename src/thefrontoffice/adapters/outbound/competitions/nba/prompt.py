"""What the model reads about a basketball week: the prompts and every block in them.

The provider gathers; this renders. Nothing here fetches.
"""

from collections.abc import Mapping

from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Matchup

OPPONENT_KEY_PLAYERS = 12
"""Enough of the other roster to name its threats without listing its bench."""

NBA_SCOUT_PROMPT = """
You are an elite NBA Fantasy General Manager and data analyst.
Your goal is to provide a concise, high-impact "Scout Report" for a fantasy basketball league.

LEAGUE RULES:
- This is a Category League ({categories}).
- Victory is determined by winning the majority of categories (e.g., 5-4 in a 9-cat league).
- STRATEGY: Prioritize categories that are "CLOSE" (either winning or losing by a small margin).
- DO NOT chase categories that are lost by a landslide.
- Focus on securing a 5-4 or 6-3 win; the exact score doesn't matter as much as the win.

CURRENT ROSTER (with Real-World Stats):
- NOTE: Players marked with "[IN IL SPOT]" are currently in Injured Reserve slots and DO NOT take up an active roster spot. You can recommend dropping them ONLY if the replacement player is also injured and can be placed in that IL spot.
{roster_str}

MATCHUP CONTEXT:
{matchup_context}

{schedule_context}

{trans_context}

TOP FREE AGENTS BY CATEGORY (Last 7 Days):
{fas_str}

YOUR TASK:
1. Analyze the matchup: Identify "Close" categories where a small boost could flip the category in our favor or secure a slim lead. Use specific category names (e.g., "trailing in BLK by 5").
2. Compare the underperformers on the current roster with the high-upside players on the waiver wire using the provided stats.
3. {recommendation_instructions}
4. For each recommendation, provide:
    - **Reasoning**: Why this player helps specifically in the "Close" categories identified. Factor in remaining games — players with MORE games left in the matchup period offer more stat production potential.
    - **Drop Target**: Suggest a specific player from the current roster to drop, with a clear justification (e.g., redundant stats, poor recent form, fewer games remaining, or non-active status).
5. Use a professional, tactical tone. Avoid flowery prose.

Return your analysis in the required structured form. Guidance for the fields:
- matchup_insight: name specific categories and margins (e.g. "trailing in BLK by 5"), and say
  which are worth contesting. Ignore categories lost by a landslide.
- close_categories: only the ones genuinely in play.
- targets: exactly three, most valuable first. Set games_remaining from the schedule data above,
  and 0 if it is not listed. Use action ADD when adds remain, MONITOR when they do not — a
  MONITOR entry leaves drop_player empty.
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
1. **Statistical Impact**: Net change in categories (L15/L30 days).
2. **Schedule Advantage**: Who has more games in the playoff weeks?
3. **Shutdown Risk**: Are any of the players receiving at risk of being shut down by tanking teams? Warning if so.
4. **Roster Awareness**: DO NOT recommend acquiring players that are already on my Current Roster.
5. **Verdict**: Should I accept, reject, or counter?

Return the evaluation in the required structured form. Field guidance:
- gains / losses: short labels in this league's own currency (categories here, e.g. ['REB', 'BLK']).
- impact: the net change, referencing recent form.
- schedule: how the remaining games compare, especially through the fantasy playoff weeks.
- risk: availability risk on the incoming side — shutdowns on tanking teams, injury designations.
- strategy: what to do next, including any counter worth offering.
"""

NO_MATCHUP = "No head-to-head matchup this week."


def categories(line: Mapping[str, float]) -> str:
    """A nine-category line in prompt shape: '25.3p 10.1r ... FG48.2% FT80.0% 2.1to'."""
    return " ".join(c.tagged(line[c.label]) for c in CATEGORIES if c.label in line)


def matchup(week: Matchup | None) -> str:
    """The head-to-head as the model reads it: the score, each category side by side, their threats."""
    if week is None:
        return NO_MATCHUP
    mine, theirs = week.mine.stats, week.opponent.stats
    breakdown = "".join(
        f"\n- {c.label}: {mine.get(c.yahoo_stat, 'N/A')} vs {theirs.get(c.yahoo_stat, 'N/A')}" for c in CATEGORIES
    )
    threats = ", ".join(f"{p.name} ({p.position})" for p in week.opponent_roster[:OPPONENT_KEY_PLAYERS])
    return (
        f"\nCURRENT MATCHUP: Playing against {week.opponent.name}"
        f"\nMATCHUP SCORE: You {week.mine.points} - {week.opponent.points} Opponent"
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


def schedule(week: Matchup | None, remaining_games: Mapping[str, int], projected: bool) -> str:
    """Whether projections stand behind the lines, then each club's games left in the period."""
    note = (
        "PROJECTIONS: lines marked PROJ carry projected totals for this matchup period — "
        "games, then the nine categories. Prefer them to recent form when the two disagree, "
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
    return f"{note}MATCHUP PERIOD: {week.start} to {week.end}\nREMAINING GAMES BY TEAM:\n{rows}"


def scout(
    *,
    roster: str,
    week: Matchup | None,
    free_agents: str,
    schedule_context: str,
    trans_context: str,
    adds_left: int,
) -> str:
    return NBA_SCOUT_PROMPT.format(
        categories=", ".join(c.label for c in CATEGORIES),
        roster_str=roster,
        matchup_context=matchup(week),
        fas_str=free_agents,
        schedule_context=schedule_context,
        trans_context=trans_context,
        recommendation_instructions=recommendation(adds_left),
    )


def trade(*, giving: str, receiving: str, week: Matchup | None, roster: str) -> str:
    return NBA_TRADE_PROMPT.format(
        giving_str=giving,
        receiving_str=receiving,
        matchup_context=matchup(week),
        roster_str=roster,
    )
