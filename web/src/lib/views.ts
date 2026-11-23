/**
 * The views a competition has: what each is called, which a competition offers,
 * and the one it opens on. The URL writes a view by the same id (`lib/route.ts`).
 */

/**
 * Every view a competition has, in the order the rail lists them: this week,
 * then the season, your roster, the moves that change it, the league around
 * you, and last the tool you bring players to.
 */
export const VIEWS = [
  "matchup",
  "fixtures",
  "schedule",
  "rosters",
  "free-agents",
  "trades",
  "league",
  "activity",
  "compare",
] as const;

/**
 * One vocabulary rather than two: the id in the code is the word in the URL,
 * so there is no table mapping "scout" to "matchup" for somebody to get wrong.
 */
export type View = (typeof VIEWS)[number];

/** What each view is called: in the rail, and where the assistant says what it can see. */
export const VIEW_LABELS: Record<View, string> = {
  matchup: "Matchup",
  schedule: "Schedule",
  fixtures: "Fixtures",
  rosters: "Rosters",
  trades: "Trades",
  "free-agents": "Free agents",
  activity: "Activity",
  league: "League",
  compare: "Compare",
};

/**
 * Whether a competition offers a view at all: only one that finds trades has a
 * Trades page. The rest every competition has, if only to say it is empty.
 */
export function offers(competition: { finds_trades: boolean }, view: View): boolean {
  return view !== "trades" || competition.finds_trades;
}

/** What a competition opens on, and what an unrecognized view falls back to. */
export const DEFAULT_VIEW: View = "matchup";
