/**
 * A comparison as words and as what opens it: whom it holds and how its drawer
 * is headed, what a trade opens, and what the comparison is called.
 */
import type { PlayerComparison, TradeIdea } from "@/lib/types";

/**
 * What a comparison is opened with: whom, and how to head it.
 *
 * `tags` names each player's side where the comparison came from a decision —
 * "In" and "Out" on a to-do, "Give" and "Get" on a trade — so a column says
 * which way he goes before it says anything else.
 */
export type Comparing = { ids: string[]; title?: string; tags?: Record<string, string> };

/** What a trade opens, wherever it is listed: both sides of it, what you give then what you get, each column saying which. */
export function traded<R>(idea: TradeIdea, onCompare: (comparing: Comparing) => R): (() => R) | undefined {
  const ids = [...idea.giving_ids, ...idea.receiving_ids];

  if (ids.length < 2) return undefined;

  const tags = {
    ...Object.fromEntries(idea.giving_ids.map((id) => [id, "Give"])),
    ...Object.fromEntries(idea.receiving_ids.map((id) => [id, "Get"])),
  };

  return () => onCompare({ ids, title: `Trade with ${idea.team}`, tags });
}

/** "A vs B", or "A, B vs C" past two: who a comparison is of, for its title and a Back link to it. */
export function compareLabel(comparison: PlayerComparison | undefined, fallback = "Compare"): string {
  const names = comparison?.players.map((p) => p.name) ?? [];

  return names.length ? names.join(" vs ") : fallback;
}

/**
 * Who is on which side, where the comparison has sides: "Give Flournoy, Tyson · Get Likely".
 * A trade's players are not each against each, which "A vs B vs C" says they are.
 */
export function sides(comparison: PlayerComparison | undefined, tags: Record<string, string> | undefined): string {
  if (!comparison || !tags) return "";

  const by = new Map<string, string[]>();

  for (const player of comparison.players) {
    const tag = tags[player.player_id];

    if (tag) by.set(tag, [...(by.get(tag) ?? []), player.name]);
  }

  return [...by].map(([tag, names]) => `${tag} ${names.join(", ")}`).join(" · ");
}
