/**
 * Instants as the app writes them: each arrives as an instant so it reads in
 * the viewer's own zone, and is written here, once, rather than by each card.
 */

/** "14:05" today, "Thu 14:05" on another day — a recent moment, in the viewer's own zone. */
export function moment(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return when.toDateString() === now.toDateString()
    ? time
    : `${when.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

/** "5:15 PM": a start time alone, in the viewer's own zone, for a row that already says the day. */
export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

const WEEK_MS = 6 * 86_400_000;

/**
 * When a game starts, short enough for a lineup row: "today 5:15 PM", "Thu 5:15 PM" later in the
 * week, and "Sat 6 Dec 3:00 PM" beyond it, where a weekday alone would not place it; in the
 * viewer's own zone.
 */
export function startsAt(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const far = when.getTime() - now.getTime() > WEEK_MS;

  const day =
    when.toDateString() === now.toDateString()
      ? "today"
      : when.toLocaleDateString(undefined, far ? { weekday: "short", day: "numeric", month: "short" } : { weekday: "short" });

  return `${day} ${clock(iso)}`;
}

/** "Sun 23 Nov, 1:00 PM" in the viewer's own zone. */
export function kickoff(iso: string): string {
  const when = new Date(iso);
  const day = when.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const time = when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  return `${day}, ${time}`;
}
