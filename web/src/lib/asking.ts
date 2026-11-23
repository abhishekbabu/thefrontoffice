/**
 * A question handed to the assistant from elsewhere on the page — a "Why?" —
 * and whether the assistant is open. A store for the same reason as
 * `lib/screen.ts`: the asker and the assistant are far apart in the tree.
 */
import { useSyncExternalStore } from "react";
import type { Shown } from "@/lib/screen";

/** A question somebody asked from elsewhere on the page — a "Why?" — for the assistant to send. */
export type Handed = { message: string; about: Shown[] };

let asked: Handed | null = null;
let docked = false;
const listeners = new Set<() => void>();

function changed() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);

  return () => listeners.delete(listener);
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
export function useAsked(): [Handed | null, () => void] {
  const current = useSyncExternalStore(subscribe, () => asked);

  return [
    current,
    () => {
      asked = null;

      changed();
    },
  ];
}
