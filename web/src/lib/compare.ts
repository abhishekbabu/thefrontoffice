/**
 * Who is being compared, per league: kept across pages and reloads.
 *
 * A player is added from wherever his drawer opens, and the Compare page reads
 * the same list (`components/league/compare-provider.ts`). Kept in the
 * browser, as a convenience of this viewer's: read once as the app starts,
 * written back on every change.
 */

/** The most players one comparison holds; the server holds the same line. */
export const MAX_COMPARED = 4;

const PREFIX = "compare:";

/** The key one league's comparison is kept under: `nba-yahoo:478.l.1`. */
export const scopeOf = (competition: string, league: string) => `${competition}:${league}`;

/** `ids` without repeats, cut to what one comparison holds. */
export const kept = (ids: readonly string[]) => [...new Set(ids)].slice(0, MAX_COMPARED);

/** Every league's comparison the browser holds. A private window, or blocked storage, holds none. */
export function readCompared() {
  const found = new Map<string, string[]>();

  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);

      if (!key?.startsWith(PREFIX)) continue;

      const parsed: unknown = JSON.parse(window.localStorage.getItem(key) ?? "[]");

      if (Array.isArray(parsed)) found.set(key.slice(PREFIX.length), kept(parsed.filter((id): id is string => typeof id === "string")));
    }
  } catch {
    // A private window keeps it for this page only.
    return Object.fromEntries(found);
  }

  return Object.fromEntries(found);
}

/** Keep one league's comparison for the next visit. */
export function writeCompared(scope: string, ids: readonly string[]): void {
  try {
    window.localStorage.setItem(PREFIX + scope, JSON.stringify(ids));
  } catch {
    // A private window keeps it for this page only.
    return;
  }
}
