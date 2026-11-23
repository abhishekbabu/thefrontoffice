import { useState } from "react";

/**
 * `value`, or the last one it was before it went to null.
 *
 * A drawer closing still slides out, and with nothing to show it would blank
 * for the length of the slide; the assistant off a league page keeps talking
 * about the league you were in. Held in state and adjusted during render —
 * React's way to derive from a change — rather than in a ref, which a render
 * must not read. `value` must keep its identity while it is the same: a fresh
 * object each render would be a change each render.
 */
export function useKept<T>(value: T | null | undefined): T | null {
  const [kept, setKept] = useState<T | null>(value ?? null);

  if (value != null && value !== kept) setKept(value);

  return value ?? kept;
}
