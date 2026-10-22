/**
 * How long an item can be put off for, as the page offers it.
 *
 * Relative to now, in the viewer's own clock — "tomorrow morning" means their
 * morning. Sent to the server with its offset, which keeps it in UTC.
 */
export type Snooze = { label: string; until: (now: Date) => Date };

export const SNOOZES: Snooze[] = [
  { label: "3 hours", until: (now) => new Date(now.getTime() + 3 * 3600_000) },
  { label: "Tomorrow, 8am", until: (now) => morningAfter(now, 1) },
  { label: "3 days", until: (now) => morningAfter(now, 3) },
];

/** 8am local, `days` after `now`'s date — a time to look again, not a moment to the second. */
export function morningAfter(now: Date, days: number): Date {
  const when = new Date(now);
  when.setDate(when.getDate() + days);
  when.setHours(8, 0, 0, 0);
  return when;
}

/** "Thu 08:00" — when a snoozed item comes back. */
export function until(iso: string): string {
  const when = new Date(iso);
  return `${when.toLocaleDateString([], { weekday: "short" })} ${when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}
