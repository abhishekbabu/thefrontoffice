/**
 * Numbers and times as the app writes them, for the few figures the API sends unformatted.
 *
 * Most arrive as text the provider already wrote; a planning figure — a week's
 * projection, a trade's effect — arrives as a number so it can be sorted and
 * compared, and an instant arrives as an instant so it reads in the viewer's
 * own zone. Each is written here, once, rather than by each card that shows it.
 * A minus sign is the typographic one, which lines up with the plus.
 */

/** "+1.6", "−0.4": a change, always signed. */
export function signed(value: number, digits = 1): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

/** "+1.5 pts": a change in a probability, as percentage points. */
export function percentPoints(change: number): string {
  return `${signed(change * 100)} pts`;
}

/** "91%": a probability. */
export function percent(chance: number): string {
  return `${Math.round(chance * 100)}%`;
}

/** "14:05" today, "Thu 14:05" on another day — a recent moment, in the viewer's own zone. */
export function moment(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return when.toDateString() === now.toDateString()
    ? time
    : `${when.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

/**
 * When a game in the week starts, short enough for a lineup row: "today 5:15 PM", or "Thu 5:15 PM"
 * on another day, in the viewer's own zone. A week's games are at most six days off, so the weekday
 * is enough to place one.
 */
export function startsAt(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const day = when.toDateString() === now.toDateString() ? "today" : when.toLocaleDateString(undefined, { weekday: "short" });
  return `${day} ${time}`;
}

/** "Sun 23 Nov, 1:00 PM" in the viewer's own zone. */
export function kickoff(iso: string): string {
  const when = new Date(iso);
  const day = when.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const time = when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day}, ${time}`;
}
