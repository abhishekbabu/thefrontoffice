/**
 * Calendar days as the server sends them, "2026-11-24": a day on the league's
 * own clock, not an instant, so it is read and written in UTC and never shifts
 * a day in the viewer's zone.
 */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

/** Whether a string is a calendar day the server would take: what an address names is not trusted. */
export function isDay(text: string | null): text is string {
  return text !== null && /^\d{4}-\d{2}-\d{2}$/.test(text) && !Number.isNaN(Date.parse(`${text}T00:00:00Z`));
}

/** Days since 1970, for ordering days and telling which way a step went. */
export function dayNumber(day: string): number {
  return Math.round(Date.parse(`${day}T00:00:00Z`) / DAY_MS);
}

/** The day `count` days from `day`, either way. */
export function addDays(day: string, count: number): string {
  return new Date((dayNumber(day) + count) * DAY_MS).toISOString().slice(0, 10);
}

/** "Tue 24 Nov": what somebody checks a lineup against. */
export function dayLabel(day: string): string {
  const when = new Date(`${day}T00:00:00Z`);

  return `${WEEKDAYS[when.getUTCDay()]} ${when.getUTCDate()} ${MONTHS[when.getUTCMonth()]}`;
}
