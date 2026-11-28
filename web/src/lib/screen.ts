/**
 * What is on screen, as the assistant is told it.
 *
 * The page comes from the address; anything opened over it — a player's
 * drawer — tells the assistant's provider (`components/league/assistant-provider.ts`)
 * while it is open, from wherever it lives.
 */
import { Schema } from "effect";
import type { Subject } from "@/lib/types";
import { type Route } from "@/lib/route";
import { VIEW_LABELS } from "@/lib/views";
import { wire } from "@/lib/wire";

/** Something on screen, and what to call it where the assistant shows its context. */
export const Shown = Schema.Struct({ subject: wire<Subject>(), label: Schema.String });

export type Shown = typeof Shown.Type;

/**
 * Everything on screen, the page first: what a question is asked with.
 *
 * Settings and the landing page are no page of a league, so they put nothing
 * of one on screen. The same thing opened twice is named once.
 */
export function onScreen(route: Route, opened: readonly Shown[]): Shown[] {
  const page: Shown[] =
    route.page === "competition"
      ? [{ subject: { kind: "page", key: route.view }, label: VIEW_LABELS[route.view] }]
      : [];

  const all = [...page, ...opened];

  return all.filter(
    (s, i) => all.findIndex((t) => t.subject.kind === s.subject.kind && t.subject.key === s.subject.key) === i,
  );
}
