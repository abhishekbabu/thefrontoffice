/**
 * What is on screen, as the assistant is told it.
 *
 * The page comes from the address; anything opened over it — a player's
 * drawer — registers itself here while it is open, from wherever it lives.
 * A store rather than props, because the drawer is mounted deep inside a
 * panel and the assistant beside the whole shell, and nothing between them
 * should have to carry what one tells the other.
 */
import { useEffect, useSyncExternalStore } from "react";
import type { Subject } from "@/lib/api";
import type { Route } from "@/lib/route";

/** Something on screen, and what to call it where the assistant shows its context. */
export type Shown = { subject: Subject; label: string };

/** A question somebody asked from elsewhere on the page — a "Why?" — for the assistant to send. */
export type Asked = { message: string; about: Shown[] };

let opened: Shown[] = [];
let asked: Asked | null = null;
let docked = false;
const listeners = new Set<() => void>();

function changed() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Register `shown` for as long as the calling component has it open.
 *
 * Null registers nothing, so a drawer can call this on every render and only
 * be on screen while it actually has somebody in it.
 */
export function useShown(shown: Shown | null) {
  const kind = shown?.subject.kind;
  const key = shown?.subject.key;
  const label = shown?.label;
  useEffect(() => {
    if (!kind || key === undefined || label === undefined) return;
    const entry: Shown = { subject: { kind, key }, label };
    opened = [...opened, entry];
    changed();
    return () => {
      opened = opened.filter((s) => s !== entry);
      changed();
    };
  }, [kind, key, label]);
}

/** Whatever is open over the page right now. */
export function useOpened(): Shown[] {
  return useSyncExternalStore(subscribe, () => opened);
}

/** Hand the assistant a question to open and send, with what it is about. */
export function askAssistant(message: string, about: Shown[] = []) {
  asked = { message, about };
  docked = true;
  changed();
}

/** Whether the assistant is open, and the way to open or minimize it — from it, or from a question handed to it. */
export function useAssistantOpen(): [boolean, (open: boolean) => void] {
  const open = useSyncExternalStore(subscribe, () => docked);
  return [
    open,
    (next: boolean) => {
      docked = next;
      changed();
    },
  ];
}

/** The question waiting to be sent, and the way to say it has been taken. */
export function useAsked(): [Asked | null, () => void] {
  const current = useSyncExternalStore(subscribe, () => asked);
  return [
    current,
    () => {
      asked = null;
      changed();
    },
  ];
}

/** What each page is called where the assistant names it. */
export const PAGE_LABELS: Record<string, string> = {
  week: "This week",
  league: "League",
  team: "My team",
  "free-agents": "Free agents",
};

/**
 * Everything on screen, the page first: what a question is asked with.
 *
 * Settings and the landing page are no page of a league, so they put nothing
 * of one on screen. The same thing opened twice is named once.
 */
export function onScreen(route: Route, opened: Shown[]): Shown[] {
  const page: Shown[] =
    route.page === "competition"
      ? [{ subject: { kind: "page", key: route.view }, label: PAGE_LABELS[route.view] ?? route.view }]
      : [];
  const all = [...page, ...opened];
  return all.filter(
    (s, i) => all.findIndex((t) => t.subject.kind === s.subject.kind && t.subject.key === s.subject.key) === i,
  );
}
