import { useSyncExternalStore } from "react";

/** The most players one comparison holds; the server holds the same line. */
export const MAX_COMPARED = 4;

/**
 * Who is being compared, per league: kept across pages and reloads.
 *
 * A player is added from wherever his drawer opens, and the Compare page reads
 * the same list. Kept in the browser, as a convenience of this viewer's.
 */
const listeners = new Set<() => void>();
const memory = new Map<string, string[]>();

const storageKey = (scope: string) => `compare:${scope}`;

function read(scope: string): string[] {
  if (!memory.has(scope)) memory.set(scope, stored(scope).slice(0, MAX_COMPARED));
  return memory.get(scope)!;
}

function stored(scope: string): string[] {
  try {
    const raw = window.localStorage.getItem(storageKey(scope));
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function write(scope: string, ids: string[]) {
  const kept = [...new Set(ids)].slice(0, MAX_COMPARED);
  memory.set(scope, kept);
  try {
    window.localStorage.setItem(storageKey(scope), JSON.stringify(kept));
  } catch {
    // A private window keeps it for this page only.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The players compared in one league, and the ways to change them. */
export function useCompared(competition: string, league: string) {
  const scope = `${competition}:${league}`;
  const ids = useSyncExternalStore(subscribe, () => read(scope));
  return {
    ids,
    full: ids.length >= MAX_COMPARED,
    has: (id: string) => ids.includes(id),
    add: (id: string) => write(scope, [...ids, id]),
    remove: (id: string) => write(scope, ids.filter((x) => x !== id)),
    set: (next: string[]) => write(scope, next),
  };
}
